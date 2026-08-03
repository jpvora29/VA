"""Setup callbacks: turn the form into a selection, then snapshot a deck.

``generate`` reads every Setup control, builds a selection, snapshots the
deterministic deck into a fresh document, and jumps to the canvas.
``scope_preview`` shows cheap headline figures as the filters change.
"""
from __future__ import annotations

from functools import lru_cache

from dash import ALL, Input, Output, State, no_update

from logger import get_logger
from studio.compute import FILTER_COLUMN
from studio.data import cascade_options, peer_members
from studio.page import authoring as A
from studio.page import document as D
from studio.template_fill import registry

from studio.authoring.config import BLANK, BREAKDOWNS, engine
from studio.authoring.generate import (
    _generated_assembled_tdoc,
    _generated_deck,
    _generated_tdoc,
)

log = get_logger(__name__)


def _scope_template_path(scope):
    """A concrete template ``.pptx`` for the tdoc fallback, derived from the scope choice.

    The assembled preview drives the canvas; this path only feeds the single-template
    fallback (``new_template_doc``), so a specific axis maps to its template and "all"
    maps to the overall template.
    """
    from studio.template_fill.binding_map import available, template_path

    axes = set(available())
    axis = scope if scope in {"overall", "product", "country"} else "overall"
    if axis not in axes:
        axis = "overall" if "overall" in axes else (sorted(axes)[0] if axes else None)
    try:
        return template_path(axis) if axis else registry.active_template_path()
    except Exception:  # noqa: BLE001 — fall back to whatever the registry considers active
        return registry.active_template_path()


def generation_block_reason(dataset_store, record) -> str:
    """Why Generate must not run for this data source, or "" when it may.

    A deck is premium-derived end to end (totals, YoY, rank, share of wallet),
    so custom data without a money measure can't produce one. This also stops
    the silent fallback where "My uploaded data" is selected but nothing has
    been submitted — that used to build a governed-DB deck instead.
    """
    from studio.dataset.model import premium_mapped
    from studio.dataset.repository import get_repository

    if (dataset_store or {}).get("source") != "custom":
        return ""
    if record is not None:
        return "" if premium_mapped(record) else (
            "This dataset has no Premium column and no primary measure. "
            "Map one on the Data page, then submit it."
        )
    active = (dataset_store or {}).get("active")
    saved = get_repository().get(active or "")
    if saved is None:
        return "Upload a dataset on the Data page, or switch back to the existing database."
    if not premium_mapped(saved):
        return (
            f"“{saved.name}” has no Premium column and no primary measure. "
            "Map one on the Data page, then submit it."
        )
    return f"“{saved.name}” isn't in use yet — open the Data page and choose “Use this data for the deck”."


# Filters that must NOT narrow the peer candidate list: the carrier is the subject
# (never its own peer) and the year would drop a peer just for having a quiet year.
_PEER_SCOPE_SKIP = ("carrier", "year")


def carriers_in_scope(filters, record) -> list:
    """`[{label, value}]` for every carrier that writes under the current filters.

    This is what makes the peer choices *correct*: country, region, product line and
    the rest all narrow the list, and the selected carrier is removed from it.
    """
    where = {
        FILTER_COLUMN[c]: v
        for c, v in (filters or {}).items()
        if c not in _PEER_SCOPE_SKIP and c in FILTER_COLUMN
    }
    opts = _cascade(record, ("Carrier_Group",), where).get("Carrier_Group", [])
    subject = str((filters or {}).get("carrier") or "").lower()
    return [o for o in opts if str(o.get("value", "")).lower() != subject]


# ── the three things a filter change re-derives ──────────────────────────────

# The GPR columns the Setup form filters on, in form order.
_FILTER_COLUMNS = tuple(FILTER_COLUMN.values())


def _cascade(record, columns, selected) -> dict:
    """``{column: options}`` from whichever source is in use (dataset wins over the DB)."""
    from studio.dataset.source import dataset_cascade_options

    if record is not None:
        return dataset_cascade_options(record.dataset_id, columns, selected)
    return cascade_options("gpr", columns, selected)


def cascade_filter_options(selected: dict, record) -> dict:
    """``{form filter id: options}`` — every dropdown narrowed to what the others allow.

    Pick a region and only its countries/carriers remain; pick a carrier and only the
    products, cover lines, industries and segments it writes in remain; and so on. One
    cached pass over the filter cube answers all ten columns
    (:func:`studio.data.cascade_options`).
    """
    where = {FILTER_COLUMN[c]: v for c, v in (selected or {}).items() if c in FILTER_COLUMN}
    by_column = _cascade(record, _FILTER_COLUMNS, where)
    return {fid: by_column[col] for fid, col in FILTER_COLUMN.items() if col in by_column}


def peer_panel_state(selected: dict, mode, record, options: dict):
    """``(dropdown options, wrapper style, message)`` for the peer panel.

    Existing mode shows ONLY the carrier's peer group from the Peers table, as names —
    there is nothing to choose, so the custom dropdown is hidden. Custom mode shows
    carriers that actually write under the current filters (country, region, product
    line…), never the whole database and never the subject itself. The Peers table is
    governed, so a custom dataset has no existing group and is told to pin its own.
    """
    carrier = (selected or {}).get("carrier")
    country = (selected or {}).get("country")
    opts = carriers_in_scope(selected, record)
    shown = {str(o.get("value", "")).lower() for o in opts}
    hidden = {"display": "none"}

    if mode == "custom":
        return opts, {}, A.peer_set_body(
            (), "Pick the carriers to benchmark against — the deck shows the aggregate only.",
        )
    if not carrier:
        return opts, hidden, A.peer_set_body((), "Select a carrier to see its existing peers.")
    if record is not None:
        return opts, hidden, A.peer_set_body(
            (), "Your data has no governed peer group — switch to Custom peers to benchmark.",
            tone="warn",
        )
    members = peer_members("gpr", carrier, country=_hashable(country))
    if not members:
        return opts, hidden, A.peer_set_body(
            (), f"No peer group exists for {carrier} — switch to Custom peers.", tone="warn",
        )
    # The Peers table is scope-free, so a listed peer may write nothing in the
    # chosen country/product scope. Show who counts, and name who drops out.
    in_scope = [m for m in members if str(m).lower() in shown]
    absent = [m for m in members if str(m).lower() not in shown]
    if not in_scope:
        return opts, hidden, A.peer_set_body(
            members, "None of these peers write in the current scope — widen the "
                     "filters or switch to Custom peers.", tone="warn",
        )
    note = f"{len(in_scope)} peer{'s' if len(in_scope) > 1 else ''} from the Peers table."
    if absent:
        note += f" Not writing in this scope: {', '.join(absent)}."
    return opts, hidden, A.peer_set_body(in_scope, note)


def _hashable(value):
    """A selection in a form a cache key accepts (Dash hands multi-selects over as lists)."""
    return tuple(value) if isinstance(value, list) else value


def scope_preview_body(selected: dict, record):
    """The live headline tiles for the current filters (empty until a carrier is picked)."""
    if not (selected or {}).get("carrier"):
        return A.scope_preview_empty()
    key = tuple(sorted((c, _hashable(v)) for c, v in selected.items()))
    try:
        items = _scope_figures(key, record.dataset_id if record else None)
    except Exception as exc:  # noqa: BLE001 — preview is best-effort, never blocks Setup
        log.warning("scope preview failed: %s", exc)
        return A.scope_preview_empty("Preview unavailable for this scope.")
    return A.scope_preview_card(items) if items else A.scope_preview_empty()


@lru_cache(maxsize=256)
def _scope_figures(key: tuple, dataset_id):
    """The preview's four figures, cached per scope.

    Two aggregate queries (a total and a market rank) that are pure functions of the
    selection, so revisiting a scope — which happens constantly while a user tries filter
    combinations — costs nothing the second time.
    """
    from core.analytics.library import compute_breakdown, compute_rank
    from core.analytics.types import PrimitiveArgs
    from studio.compute import _CARRIER_COL, _resolve_filters
    from studio.dataset.source import dataset_engine
    from studio.page.format import money

    filters = {c: (list(v) if isinstance(v, tuple) else v) for c, v in key}
    eng = dataset_engine(dataset_id) if dataset_id else engine
    resolved = _resolve_filters(filters)
    subject = resolved.get(_CARRIER_COL)

    total_facts = compute_breakdown(
        PrimitiveArgs(flow="gpr", metric="premium", group_by=(), filters=resolved), engine=eng
    )
    total = total_facts[0].value if total_facts else 0.0
    rank_filters = {k: v for k, v in resolved.items() if k != _CARRIER_COL}
    rank_facts = compute_rank(
        PrimitiveArgs(flow="gpr", metric="premium", group_by=(), filters=rank_filters), engine=eng
    )
    mine = next((f for f in rank_facts
                 if str(f.dims.get("entity", "")).lower() == str(subject).lower()), None)

    country = filters.get("country")
    n_countries = len(country) if isinstance(country, (list, tuple)) else (1 if country else "All")
    year_val = filters.get("year")
    if isinstance(year_val, (list, tuple, set)):
        years = sorted(str(y) for y in year_val if str(y).strip())
        year_disp = ", ".join(years) if years else "All"
    else:
        year_disp = str(year_val) if year_val else "All"
    return (
        {"label": "Total GWP", "value": money(total), "sub": str(subject)},
        {"label": "Market rank", "value": (mine.rendered if mine else "—")},
        {"label": "Countries", "value": str(n_countries)},
        {"label": "Year", "value": year_disp},
    )


def _generation_blocked(dataset_store, record):
    """The block reason as a rendered warning, or None when generation may run."""
    from dash import html

    reason = generation_block_reason(dataset_store, record)
    return html.Span(reason, className="qs-map-hint warn") if reason else None


def register_setup(app):
    """Wire the Generate + scope-preview callbacks onto ``app``."""

    @app.callback(
        Output("qs-selection", "data"),
        Output("qs-doc", "data", allow_duplicate=True),
        Output("qs-tdoc", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Output("qs-generating", "data"),
        Output("studio-setup-msg", "children"),
        Input("studio-generate", "n_clicks"),
        State({"type": "studio-filter", "col": ALL}, "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State({"type": "studio-cut", "name": ALL}, "value"),
        State({"type": "studio-cut", "name": ALL}, "id"),
        State("studio-peer-mode", "value"),
        State("studio-peer-custom", "value"),
        State("studio-audience", "value"),
        State("studio-commentary-style", "value"),
        State("studio-ai-toggle", "value"),
        State("studio-template", "value"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def generate(n, fvals, fids, cut_vals, cut_ids, peer_mode, custom_peers,
                 audience, style, ai, template_scope, dataset_store):
        if not n:
            return no_update, no_update, no_update, no_update, no_update, no_update
        from studio.dataset.source import dataset_in_use

        filters = {i["col"]: v for i, v in zip(fids or [], fvals or []) if v not in BLANK}
        cuts = [i["name"] for i, v in zip(cut_ids or [], cut_vals or []) if v]
        # Custom peers apply directly: the authoring Setup has no ANALYSES
        # checkboxes, so gating on a "peer_average" cut left the panel dead —
        # peer benchmarks in the filled template use this pinned set (or the
        # Peers table when the mode is "existing").
        peers = None
        if peer_mode == "custom":
            peers = [p for p in (custom_peers or []) if p] or None
        # A submitted custom dataset pins its id into the selection: every cached
        # build (deck / tdoc / assembled) then keys and computes on THAT data.
        record = dataset_in_use(dataset_store)
        blocked = _generation_blocked(dataset_store, record)
        if blocked:
            return no_update, no_update, no_update, no_update, no_update, blocked
        selection = {
            # Full QBR is the only deliverable, so the Setup form no longer asks.
            "report": "qbr",
            "filters": filters,
            # The breakdown control was removed from Setup; the deck keeps the deterministic
            # default breakdowns so the on-screen DeckSpec still has its sections.
            "breakdowns": BREAKDOWNS,
            "cuts": cuts,
            "peers": peers,
            "audience": audience or "executive",
            "meeting_length": "standard",
            "style": style or "balanced",
            "ai": bool(ai),
            "template_scope": template_scope or "all",
            "template_path": _scope_template_path(template_scope),
            "dataset_id": record.dataset_id if record else None,
        }
        deck = _generated_deck(selection)
        doc = D.new_document(deck) if deck else None
        # Preview the ASSEMBLED deck (overall + per product + per country); fall back to the
        # single-template doc only if assembly can't run.
        tdoc = _generated_assembled_tdoc(selection) or _generated_tdoc(selection)
        return selection, doc, tdoc, {"mode": "canvas", "idx": 0, "tab": "setup"}, n, ""

    # A filter change used to fire THREE callbacks that each re-queried the warehouse. They
    # are now split by COST, not by panel:
    #
    #   * the form itself — options + peer panel — is answered from the cached filter cube,
    #     so it is a couple of milliseconds and needs no spinner;
    #   * the scope preview runs two real aggregates (a total and a market rank), which no
    #     cube can shortcut, so it stays a SEPARATE callback. The browser runs the two
    #     concurrently, and the slow one can never hold up the fast one — merging them made
    #     every dropdown wait on the rank query.
    @app.callback(
        Output({"type": "studio-filter", "col": ALL}, "options"),
        Output("studio-peer-custom", "options"),
        Output("studio-peer-custom-wrap", "style"),
        Output("studio-peer-msg", "children"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        Input("studio-peer-mode", "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State("qs-dataset", "data"),
    )
    def refresh_form(values, mode, ids, dataset_store):
        """Re-derive every dropdown's options and the peer panel — one cube pass."""
        from studio.dataset.source import dataset_in_use

        ids = ids or []
        selected = {i["col"]: v for i, v in zip(ids, values or []) if v not in BLANK}
        record = dataset_in_use(dataset_store)
        options = cascade_filter_options(selected, record)
        peer_opts, peer_style, peer_msg = peer_panel_state(selected, mode, record, options)
        return [options.get(i["col"], no_update) for i in ids], peer_opts, peer_style, peer_msg

    @app.callback(
        Output("studio-scope-preview", "children"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State("qs-dataset", "data"),
    )
    def scope_preview(values, ids, dataset_store):
        """The live headline figures — the one panel that genuinely queries on each change."""
        from studio.dataset.source import dataset_in_use

        selected = {i["col"]: v for i, v in zip(ids or [], values or []) if v not in BLANK}
        return scope_preview_body(selected, dataset_in_use(dataset_store))
