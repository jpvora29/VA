"""Build a deck or a filled template-doc from a Setup selection.

These are pure helpers — given a selection (or a document) they return a
``DeckSpec`` / template-doc / assembled ``.pptx`` path. They hold no UI state,
so the callback modules can call them freely. Results are cached by selection so
Generate does the work once and Export re-serves the same artifact.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from studio.compute import FILTER_COLUMN, compute_overall
from studio.data import cached_filter_options
from studio.deck import build_deck
from studio.memo import build_memo
from studio.deck.model import DeckSpec
from studio.page import document as D
from studio.template_fill import new_template_doc
from studio.template_fill.preview_assets import (
    eager_slide_limit,
    ensure_doc_backgrounds,
    ensure_rendered_slide_backgrounds,
    prune_cache,
)

from logger import get_logger
from studio.authoring.config import BLANK, BREAKDOWNS, engine
from studio.authoring.progress import Reporter, silent
from studio.content.report_plan import DEFAULT_AUDIENCE

log = get_logger(__name__)


# ── small value helpers ───────────────────────────────────────────────────────


def _friendly_options(dataset_store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Filter options keyed back to the form's friendly ids (region, carrier…).

    When a submitted custom dataset is in use, the options derive from ITS
    materialized table — every dropdown reflects exactly what the user uploaded;
    otherwise the governed DB's cached distincts."""
    from studio.dataset.source import dataset_filter_options, dataset_in_use

    record = dataset_in_use(dataset_store)
    if record is not None:
        return dataset_filter_options(record.dataset_id, FILTER_COLUMN)
    col_opts = cached_filter_options("gpr")
    return {fid: col_opts.get(col, []) for fid, col in FILTER_COLUMN.items()}


def _engine_for(selection: Dict[str, Any]):
    """The analytics source a selection computes against.

    The governed engine by default; a submitted dataset's FRAMES when the selection
    pins a ``dataset_id``, which routes every primitive to the pandas executor (see
    ``studio.dataset.source.dataset_source``). The id lives inside the selection JSON,
    so every lru_cache key already varies.
    """
    dataset_id = (selection or {}).get("dataset_id")
    if dataset_id:
        from studio.dataset.source import dataset_source

        return dataset_source(dataset_id)
    return engine


def _one(value):
    """Unwrap a single-element multi-select list to a scalar for clean display."""
    if isinstance(value, (list, tuple)):
        return value[0] if len(value) == 1 else ", ".join(str(v) for v in value)
    return value


def _latest_year(value):
    """The reporting year passed to the content spec — MAX of a multi-select year."""
    if isinstance(value, (list, tuple)):
        years = [int(v) for v in value if str(v).strip().isdigit()]
        return max(years) if years else None
    return value


def _selection_filters(selection: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in ((selection or {}).get("filters") or {}).items() if v not in BLANK}


def usable_tdoc(tdoc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The persisted template doc, or ``None`` when its ``.pptx`` no longer exists.

    ``qs-tdoc`` lives in browser local storage, so it survives app restarts — but an
    ASSEMBLED doc's ``template_path`` points into the system temp dir, which Windows
    cleans between sessions. Rendering such a doc crashes the master render callback
    (``derive_manifest`` reads the file bytes), so a doc whose file is gone is dropped
    and the app opens on Setup; the selection is persisted too, so Generate rebuilds it.
    """
    if not tdoc:
        return None
    path = tdoc.get("template_path")
    if path and not Path(path).exists():
        log.warning("stale template doc dropped (file missing): %s", path)
        return None
    return tdoc


# ── the on-screen deck (a generated deck, or the edited document) ─────────────


@lru_cache(maxsize=8)
def _result_for(selection_json: str):
    """The analytics result a selection computes to — ONCE per selection.

    The on-screen deck, the single-template document and the assembled deck are three
    views of one answer, and each used to compute it for itself: a Generate ran the whole
    analytics layer twice before it wrote a word. They all key on the same frozen
    selection, so they can all read the same cached result.
    """
    sel = json.loads(selection_json)
    filters = {k: v for k, v in (sel.get("filters") or {}).items() if v not in BLANK}
    return compute_overall(
        filters=filters,
        breakdowns=sel.get("breakdowns") or BREAKDOWNS,
        engine=_engine_for(sel),
        peers=sel.get("peers") or None,
        peers_by_country=sel.get("peers_by_country") or None,
        style=sel.get("style") or "balanced",
        survey_carrier=sel.get("survey_carrier") or None,
        survey_peers=sel.get("survey_peers") or None,
        survey_peers_by_country=sel.get("survey_peers_by_country") or None,
    )


@lru_cache(maxsize=64)
def _deck_for(selection_json: str) -> Optional[DeckSpec]:
    """Build the generated deck for a frozen selection (JSON key → hashable)."""
    sel = json.loads(selection_json)
    filters = {k: v for k, v in (sel.get("filters") or {}).items() if v not in BLANK}
    result = _result_for(selection_json)
    return build_deck(
        result,
        carrier=_one(filters.get("carrier")),
        country=_one(filters.get("country")),
        year=_latest_year(filters.get("year")),
        report=sel.get("report") or "qbr",
        cuts=tuple(sel.get("cuts") or ()),
        ai=bool(sel.get("ai")),
        audience=sel.get("audience") or DEFAULT_AUDIENCE,
        meeting_length=sel.get("meeting_length") or "standard",
    )


def _generated_deck(selection: Optional[Dict[str, Any]]) -> Optional[DeckSpec]:
    if not selection or not selection.get("filters", {}).get("carrier"):
        return None
    try:
        return _deck_for(json.dumps(selection, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 — a bad selection must not white-screen the app
        log.warning("deck build failed: %s", exc)
        return None


def _deck(doc) -> Optional[DeckSpec]:
    """The on-screen deck = the document materialized (edits + page order applied)."""
    try:
        return D.materialize(doc)
    except Exception as exc:  # noqa: BLE001 — tolerate a stale persisted doc shape
        log.warning("materialize failed: %s", exc)
        return None


# ── the template doc (single template, filled from the same result) ──────────


@lru_cache(maxsize=32)
def _tdoc_for(selection_json: str) -> Optional[Dict[str, Any]]:
    """Seed a template doc (active template, filled from the same OverallResult)."""
    sel = json.loads(selection_json)
    return new_template_doc(_result_for(selection_json),
                            template_path=sel.get("template_path") or None,
                            use_ai=bool(sel.get("ai")))


def _generated_tdoc(selection: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not selection or not selection.get("filters", {}).get("carrier"):
        return None
    try:
        return _with_background_urls(_tdoc_for(json.dumps(selection, sort_keys=True)))
    except Exception as exc:  # noqa: BLE001 — template issues must not white-screen the app
        log.warning("template doc build failed: %s", exc)
        return None


def _with_background_urls(tdoc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Attach pre-rendered backgrounds during Generate, never during navigation."""
    if not tdoc or tdoc.get("background_urls"):
        return tdoc
    n = int(tdoc.get("n_slides") or len(tdoc.get("order") or []))
    if not n:
        return tdoc
    try:
        return {**tdoc, "background_urls": ensure_doc_backgrounds(dict(tdoc), n)}
    except Exception as exc:  # noqa: BLE001
        log.warning("template background render failed: %s", exc)
        return tdoc


# ── the assembled deck (overall + per product + per country, merged) ─────────


@lru_cache(maxsize=8)
def _assembled_for(selection_json: str) -> Optional[str]:
    """Assemble the full deck (overall + per product + per country) for a selection, once.

    Cached by selection so Generate builds it and Export just re-serves the same file. The
    filename embeds a selection hash so different filter sets don't collide in the render/
    download cache. Returns the merged ``.pptx`` path, or ``None`` if it can't run.
    """
    selection = json.loads(selection_json)
    filters = _selection_filters(selection)
    if not filters.get("carrier"):
        return None
    from studio.template_fill.assemble import assemble_deck

    result = _result_for(selection_json)
    subject = str(filters.get("carrier", "Carrier")).replace(" ", "_")
    tag = hashlib.sha1(selection_json.encode("utf-8")).hexdigest()[:8]
    out = Path(tempfile.gettempdir()) / f"{subject}_{tag}_QBR.pptx"
    return assemble_deck(result, out_path=str(out), scope=selection.get("template_scope"),
                         data_basis=selection.get("data_basis"))


def _assembled_export(selection: Optional[Dict[str, Any]]) -> Optional[str]:
    if not selection or not _selection_filters(selection).get("carrier"):
        return None
    key = json.dumps(selection, sort_keys=True)
    path = _assembled_for(key)
    if path and not Path(path).exists():
        # The cached path outlived its temp file (Windows temp cleanup) — rebuild.
        _assembled_for.cache_clear()
        path = _assembled_for(key)
    return path


def _assembled_tdoc(selection: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Wrap the assembled deck as a read-only preview doc (pages through ALL its slides).

    The deck is already filled, so the doc carries no editable manifest — the preview just
    renders the merged slides (overall + product + country), and Export re-serves the file.
    """
    path = _assembled_export(selection)
    if not path:
        return None
    from studio.template_fill.analyze import analyze

    template = analyze(path)
    n = len(template.slides)
    try:
        # Only the opening slides. The canvas shows ONE page at a time, so
        # rendering all of them here made the author wait on ~0.5s of PowerPoint
        # per slide for pages they had not asked to see — minutes on a full QBR.
        # The rest render as they navigate (`template_preview_body`), and an
        # unrendered page falls back to its geometry rather than to nothing.
        background_urls = ensure_rendered_slide_backgrounds(
            path, n, only=range(eager_slide_limit()) if eager_slide_limit() >= 0 else None
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("assembled preview render failed: %s", exc)
        background_urls = [None] * n
    # Every deck ever generated left a full-resolution render of every slide behind in
    # ``assets/``, and nothing removed them. Now that THIS deck's images exist, the ones
    # belonging to decks nobody is looking at any more go.
    try:
        prune_cache([path])
    except Exception as exc:  # noqa: BLE001 — housekeeping must never cost us the deck
        log.warning("preview cache prune failed: %s", exc)
    return {
        "template_path": path,
        "values": {},
        "manifest": [],
        "overrides": {},
        "map_overrides": {},
        "added": {},
        "hidden": [],
        "order": list(range(n)),
        "width_emu": template.width_emu,
        "height_emu": template.height_emu,
        "n_slides": n,
        "assembled": True,
        "background_urls": background_urls,
    }


def _generated_assembled_tdoc(selection: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not selection or not selection.get("filters", {}).get("carrier"):
        return None
    try:
        return _assembled_tdoc(selection)
    except Exception as exc:  # noqa: BLE001 — a bad assembly must not white-screen the app
        log.warning("assembled preview build failed: %s", exc)
        return None


# ── the whole build, as one reportable pipeline ──────────────────────────────


@dataclass(frozen=True)
class DeckDocuments:
    """What one Generate produces: the editable document, and the template preview."""

    doc: Optional[Dict[str, Any]] = None
    tdoc: Optional[Dict[str, Any]] = None

    @property
    def empty(self) -> bool:
        return self.doc is None and self.tdoc is None


def build_documents(selection: Optional[Dict[str, Any]],
                    report: Reporter = silent) -> DeckDocuments:
    """Everything Generate needs, built once, announcing each phase as it starts.

        the book  ->  the on-screen deck  ->  the assembled deck  ->  its slide images

    Every step reads the ONE analytics result for this selection (:func:`_result_for`),
    so the four phases below are four views of one query pass rather than four of them.
    ``report`` is how a caller follows a build that takes minutes — see
    :mod:`studio.authoring.jobs`; scripts and tests pass nothing and get silence.
    """
    key = json.dumps(selection or {}, sort_keys=True)

    # ONE memo for the whole build. The on-screen deck and the assembled deck ask the
    # warehouse the same questions about the same scopes; measured, 217 of 305
    # primitive calls in a single-country build were exact repeats. `assemble_deck`
    # opens its own memo and `build_memo` is re-entrant, so that inner one shares this
    # cache rather than starting a second. It is discarded when the build returns.
    with build_memo(f"generate:{(selection or {}).get('filters', {}).get('carrier') or 'deck'}"):
        report("data", "Loading the book for this selection…")
        _result_for(key)

        report("deck", "Laying out the deck…")
        deck = _generated_deck(selection)
        doc = D.new_document(deck) if deck else None

        # The ASSEMBLED deck (overall + per product + per country) is the deliverable
        # and what the canvas previews; the single filled template is the fallback for a
        # template set that cannot assemble. Both phases are announced here rather than
        # inside, because assembling is where a build spends its minutes and the author
        # should see that.
        report("assemble", "Writing the commentary and filling the templates…")
        tdoc = _generated_assembled_tdoc(selection) or _generated_tdoc(selection)

    report("render", "Rendering the slides…")
    return DeckDocuments(doc=doc, tdoc=tdoc)
