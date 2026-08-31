"""Tab switching: a click writes ``active-tab``; ``active-tab`` re-dresses the shell.

Two callbacks, split on purpose. The click handler only records intent, so anything
else that wants to change workspace (a deep link, a "open this in Studio" button) can
write the store and get the same result. The paint handler only reads the store, so it
is the single place that knows a pane is hidden by a class rather than unmounted.

Nothing is torn down on a switch: a half-built deck, an unsent message and a running
chat turn all survive a trip to another tab and back.
"""
from __future__ import annotations

from typing import Any, List, Tuple

from dash import ALL, Input, Output, State, ctx, no_update

from ui.shell.navbar import tab_class
from ui.shell.tabs import TABS, pane_class, pane_id, resolve_tab


def register_router(app) -> None:
    """Wire the navbar tabs to the pane visibility on ``app``."""

    @app.callback(
        Output("active-tab", "data"),
        Input({"type": "va-tab", "tab": ALL}, "n_clicks"),
        State("active-tab", "data"),
        prevent_initial_call=True,
    )
    def select_tab(clicks: List[int], current: str | None) -> Any:
        """Record which workspace the user asked for."""
        if not ctx.triggered_id or not any(clicks or []):
            return no_update
        chosen = resolve_tab(ctx.triggered_id["tab"])
        return no_update if chosen == resolve_tab(current) else chosen

    @app.callback(
        [Output(pane_id(t.id), "className") for t in TABS]
        + [Output({"type": "va-tab", "tab": t.id}, "className") for t in TABS],
        Input("active-tab", "data"),
    )
    def paint_tabs(active: str | None) -> Tuple[str, ...]:
        """Show the active pane, hide the rest, and light its navbar tab."""
        active = resolve_tab(active)
        return tuple(
            [pane_class(t.id, active) for t in TABS]
            + [tab_class(t.id, active) for t in TABS]
        )
