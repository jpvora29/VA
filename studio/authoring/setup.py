"""Setup callbacks: turn the form into a selection, then snapshot a deck.

``generate`` reads every Setup control, builds a selection, snapshots the
deterministic deck into a fresh document, and jumps to the canvas.
``scope_preview`` shows cheap headline figures as the filters change.
"""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, no_update

from logger import get_logger
from studio.compute import FILTER_COLUMN
from studio.data import dependent_options, peer_members
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


def register_setup(app):
    """Wire the Generate + scope-preview callbacks onto ``app``."""

    @app.callback(
        Output("qs-selection", "data"),
        Output("qs-doc", "data", allow_duplicate=True),
        Output("qs-tdoc", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Output("qs-generating", "data"),
        Input("studio-generate", "n_clicks"),
        State("studio-report-type", "value"),
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
    def generate(n, report, fvals, fids, cut_vals, cut_ids, peer_mode, custom_peers,
                 audience, style, ai, template_scope, dataset_store):
        if not n:
            return no_update, no_update, no_update, no_update, no_update
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
        selection = {
            "report": report or "qbr",
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
        return selection, doc, tdoc, {"mode": "canvas", "idx": 0, "tab": "setup"}, n

    @app.callback(
        Output({"type": "studio-filter", "col": ALL}, "options"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State("qs-dataset", "data"),
    )
    def cascade_filters(values, ids, dataset_store):
        """Narrow every filter's options to what the OTHER selections allow.

        Pick a region and only its countries/carriers remain; pick a carrier and only the
        products, cover lines, industries and segments it writes in remain; and so on.
        Governed source: cached DB distincts (``dependent_options``). Custom source: the
        same cascade computed on the submitted dataset's materialized table.
        """
        from studio.dataset.source import dataset_dependent_options, dataset_in_use

        ids = ids or []
        selected = {i["col"]: v for i, v in zip(ids, values or []) if v not in BLANK}
        record = dataset_in_use(dataset_store)
        out = []
        for i in ids:
            col = i["col"]
            gcol = FILTER_COLUMN.get(col)
            if not gcol:
                out.append(no_update)
                continue
            where = {
                FILTER_COLUMN[c]: v
                for c, v in selected.items()
                if c != col and c in FILTER_COLUMN
            }
            if record is not None:
                out.append(dataset_dependent_options(record.dataset_id, gcol, where))
            else:
                out.append(dependent_options("gpr", gcol, where))
        return out

    @app.callback(
        Output("studio-peer-custom", "options"),
        Output("studio-peer-msg", "children"),
        Input({"type": "studio-filter", "col": "carrier"}, "value"),
        Input({"type": "studio-filter", "col": "country"}, "value"),
        Input("studio-peer-mode", "value"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def peer_panel(carrier, country, mode, dataset_store):
        """Populate custom-peer options and the existing-peers message.

        This callback existed only in the demo app, which left the authoring
        Setup's peer panel dead. Options track the active data source; the
        Peers table itself stays governed, so with custom data the existing-
        peers mode explains that custom peers are the way."""
        from studio.dataset.source import dataset_dependent_options, dataset_in_use

        record = dataset_in_use(dataset_store)
        where = {"Country": country} if country not in (None, "", [], "all", "All") else None
        if record is not None:
            opts = dataset_dependent_options(record.dataset_id, "Carrier_Group", where)
        else:
            opts = dependent_options("gpr", "Carrier_Group", where)
        if mode == "custom":
            return opts, "Pick the peers to benchmark against — output shows the aggregate only."
        if not carrier:
            return opts, "Select a carrier to see its existing peers."
        if record is not None:
            return opts, "Your data has no governed peer group — switch to Custom peers to benchmark."
        members = peer_members("gpr", carrier, country=country)
        if members:
            shown = ", ".join(members[:8]) + ("…" if len(members) > 8 else "")
            return opts, f"Existing peers ({len(members)}): {shown}"
        return opts, "No peers exist for this carrier — switch to Custom peers."

    @app.callback(
        Output("studio-scope-preview", "children"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
        State("qs-dataset", "data"),
    )
    def scope_preview(values, ids, dataset_store):
        filters = {i["col"]: v for i, v in zip(ids or [], values or []) if v not in BLANK}
        if not filters.get("carrier"):
            return A.scope_preview_empty()
        try:
            from core.analytics.library import compute_breakdown, compute_rank
            from core.analytics.types import PrimitiveArgs
            from studio.compute import _CARRIER_COL, _resolve_filters
            from studio.dataset.source import dataset_engine, dataset_in_use
            from studio.page.format import money

            record = dataset_in_use(dataset_store)
            eng = dataset_engine(record.dataset_id) if record else engine
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
            mine = next((f for f in rank_facts if str(f.dims.get("entity", "")).lower() == str(subject).lower()), None)
            country = filters.get("country")
            n_countries = len(country) if isinstance(country, (list, tuple)) else (1 if country else "All")
            year_val = filters.get("year")
            if isinstance(year_val, (list, tuple, set)):
                years = sorted(str(y) for y in year_val if str(y).strip())
                year_disp = ", ".join(years) if years else "All"
            else:
                year_disp = str(year_val) if year_val else "All"
            items = [
                {"label": "Total GWP", "value": money(total), "sub": str(subject)},
                {"label": "Market rank", "value": (mine.rendered if mine else "—")},
                {"label": "Countries", "value": str(n_countries)},
                {"label": "Year", "value": year_disp},
            ]
            return A.scope_preview_card(items)
        except Exception as exc:  # noqa: BLE001 — preview is best-effort, never blocks Setup
            log.warning("scope preview failed: %s", exc)
            return A.scope_preview_empty("Preview unavailable for this scope.")
