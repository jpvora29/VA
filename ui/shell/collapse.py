"""Collapsing the left rail: any rail's toggle flips one app-wide state.

Split from the tab router because it answers a different question — the router decides
*which* workspace is on screen, this decides *how wide the rail is* in all of them.

Two callbacks, for the same reason the router has two: the click handler only records
intent, so anything else that wants to collapse the rail can write the store; the paint
handler only reads it, so it is the single place that knows the state is expressed as a
class on the pane container rather than on the rails themselves (see ``ui.shell.rail``).
"""
from __future__ import annotations

from typing import Any, List, Tuple

from dash import ALL, Input, Output, State, ctx, no_update

from ui.shell.rail import rails_class


def _total_clicks(clicks: List[Any]) -> int:
    return sum(int(c or 0) for c in clicks)


def register_collapse(app) -> None:
    """Wire every rail's collapse toggle to the shared rail width on ``app``."""

    @app.callback(
        Output("rail-collapsed", "data"),
        Output("rail-toggle-clicks", "data"),
        Input({"type": "va-rail-toggle", "rail": ALL}, "n_clicks"),
        State("rail-collapsed", "data"),
        State("rail-toggle-clicks", "data"),
        prevent_initial_call=True,
    )
    def toggle_rail(clicks: List[Any], collapsed: Any, seen: Any) -> Tuple[Any, int]:
        """Any rail's toggle flips the state for all of them.

        A pattern-matching Input also fires when the set of matching components
        CHANGES, not only when one is clicked — and Studio rebuilds its whole rail
        (toggle included, ``n_clicks`` back to 0) on every mode change. Counting
        clicks is what tells a real press apart from a rail being remounted;
        without it, navigating Studio after one toggle press would flip the rail
        again on every step.
        """
        total = _total_clicks(clicks)
        if not ctx.triggered_id or total <= int(seen or 0):
            return no_update, total
        return not bool(collapsed), total

    @app.callback(
        Output("va-body", "className"),
        Input("rail-collapsed", "data"),
    )
    def paint_rails(collapsed: Any) -> str:
        """One class on the pane container widens or narrows every rail at once."""
        return rails_class(bool(collapsed))
