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
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from studio.compute import FILTER_COLUMN, compute_overall
from studio.data import cached_filter_options
from studio.deck import build_deck
from studio.deck.model import DeckSpec
from studio.page import document as D
from studio.template_fill import new_template_doc
from studio.template_fill.preview_assets import ensure_doc_backgrounds, ensure_rendered_slide_backgrounds

from logger import get_logger
from studio.authoring.config import BLANK, BREAKDOWNS, engine

log = get_logger(__name__)


# ── small value helpers ───────────────────────────────────────────────────────


def _friendly_options() -> Dict[str, Any]:
    """DB filter options keyed back to the form's friendly ids (region, carrier…)."""
    col_opts = cached_filter_options("gpr")
    return {fid: col_opts.get(col, []) for fid, col in FILTER_COLUMN.items()}


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


# ── the on-screen deck (a generated deck, or the edited document) ─────────────


@lru_cache(maxsize=64)
def _deck_for(selection_json: str) -> Optional[DeckSpec]:
    """Build the generated deck for a frozen selection (JSON key → hashable)."""
    sel = json.loads(selection_json)
    filters = {k: v for k, v in (sel.get("filters") or {}).items() if v not in BLANK}
    result = compute_overall(
        filters=filters,
        breakdowns=sel.get("breakdowns") or BREAKDOWNS,
        engine=engine,
        peers=sel.get("peers") or None,
    )
    return build_deck(
        result,
        carrier=_one(filters.get("carrier")),
        country=_one(filters.get("country")),
        year=_latest_year(filters.get("year")),
        report=sel.get("report") or "qbr",
        cuts=tuple(sel.get("cuts") or ()),
        ai=bool(sel.get("ai")),
        audience=sel.get("audience") or "executive",
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
    filters = {k: v for k, v in (sel.get("filters") or {}).items() if v not in BLANK}
    result = compute_overall(
        filters=filters,
        breakdowns=sel.get("breakdowns") or BREAKDOWNS,
        engine=engine,
        peers=sel.get("peers") or None,
    )
    return new_template_doc(result, template_path=sel.get("template_path") or None,
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

    result = compute_overall(
        filters=filters,
        breakdowns=selection.get("breakdowns") or BREAKDOWNS,
        engine=engine,
        peers=selection.get("peers") or None,
    )
    subject = str(filters.get("carrier", "Carrier")).replace(" ", "_")
    tag = hashlib.sha1(selection_json.encode("utf-8")).hexdigest()[:8]
    out = Path(tempfile.gettempdir()) / f"{subject}_{tag}_QBR.pptx"
    return assemble_deck(result, out_path=str(out))


def _assembled_export(selection: Optional[Dict[str, Any]]) -> Optional[str]:
    if not selection or not _selection_filters(selection).get("carrier"):
        return None
    return _assembled_for(json.dumps(selection, sort_keys=True))


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
        background_urls = ensure_rendered_slide_backgrounds(path, n)
    except Exception as exc:  # noqa: BLE001
        log.warning("assembled preview render failed: %s", exc)
        background_urls = [None] * n
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
