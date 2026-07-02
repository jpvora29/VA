"""Setup callbacks: turn the form into a selection, then snapshot a deck.

``generate`` reads every Setup control, builds a selection, snapshots the
deterministic deck into a fresh document, and jumps to the canvas.
``scope_preview`` shows cheap headline figures as the filters change.
"""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, no_update

from logger import get_logger
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
        State("studio-breakdown", "value"),
        State({"type": "studio-cut", "name": ALL}, "value"),
        State({"type": "studio-cut", "name": ALL}, "id"),
        State("studio-peer-mode", "value"),
        State("studio-peer-custom", "value"),
        State("studio-audience", "value"),
        State("studio-meeting-length", "value"),
        State("studio-ai-toggle", "value"),
        State("studio-template", "value"),
        prevent_initial_call=True,
    )
    def generate(n, report, fvals, fids, breakdowns, cut_vals, cut_ids, peer_mode, custom_peers,
                 audience, meeting_length, ai, template_path):
        if not n:
            return no_update, no_update, no_update, no_update, no_update
        filters = {i["col"]: v for i, v in zip(fids or [], fvals or []) if v not in BLANK}
        cuts = [i["name"] for i, v in zip(cut_ids or [], cut_vals or []) if v]
        peers = None
        if "peer_average" in cuts and peer_mode == "custom":
            peers = [p for p in (custom_peers or []) if p]
        selection = {
            "report": report or "qbr",
            "filters": filters,
            "breakdowns": breakdowns or BREAKDOWNS,
            "cuts": cuts,
            "peers": peers,
            "audience": audience or "executive",
            "meeting_length": meeting_length or "standard",
            "ai": bool(ai),
            "template_path": template_path or registry.active_template_path(),
        }
        deck = _generated_deck(selection)
        doc = D.new_document(deck) if deck else None
        # Preview the ASSEMBLED deck (overall + per product + per country); fall back to the
        # single-template doc only if assembly can't run.
        tdoc = _generated_assembled_tdoc(selection) or _generated_tdoc(selection)
        return selection, doc, tdoc, {"mode": "canvas", "idx": 0, "tab": "setup"}, n

    @app.callback(
        Output("studio-scope-preview", "children"),
        Input({"type": "studio-filter", "col": ALL}, "value"),
        State({"type": "studio-filter", "col": ALL}, "id"),
    )
    def scope_preview(values, ids):
        filters = {i["col"]: v for i, v in zip(ids or [], values or []) if v not in BLANK}
        if not filters.get("carrier"):
            return A.scope_preview_empty()
        try:
            from core.analytics.library import compute_breakdown, compute_rank
            from core.analytics.types import PrimitiveArgs
            from studio.compute import _CARRIER_COL, _resolve_filters
            from studio.page.format import money

            resolved = _resolve_filters(filters)
            subject = resolved.get(_CARRIER_COL)
            total_facts = compute_breakdown(
                PrimitiveArgs(flow="gpr", metric="premium", group_by=(), filters=resolved), engine=engine
            )
            total = total_facts[0].value if total_facts else 0.0
            rank_filters = {k: v for k, v in resolved.items() if k != _CARRIER_COL}
            rank_facts = compute_rank(
                PrimitiveArgs(flow="gpr", metric="premium", group_by=(), filters=rank_filters), engine=engine
            )
            mine = next((f for f in rank_facts if str(f.dims.get("entity", "")).lower() == str(subject).lower()), None)
            country = filters.get("country")
            n_countries = len(country) if isinstance(country, (list, tuple)) else (1 if country else "All")
            items = [
                {"label": "Total GWP", "value": money(total), "sub": str(subject)},
                {"label": "Market rank", "value": (mine.rendered if mine else "—")},
                {"label": "Countries", "value": str(n_countries)},
                {"label": "Year", "value": str(filters.get("year") or "All")},
            ]
            return A.scope_preview_card(items)
        except Exception as exc:  # noqa: BLE001 — preview is best-effort, never blocks Setup
            log.warning("scope preview failed: %s", exc)
            return A.scope_preview_empty("Preview unavailable for this scope.")
