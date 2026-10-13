"""Present callback: open the slideshow over Studio, and take it down again.

Paging through the show happens in the browser (assets/studio_present.js); the only
server work is building the show — rendering any page that has no picture yet — and
clearing it when the author ends it.
"""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, no_update

from logger import get_logger
from studio.authoring.generate import usable_tdoc
from studio.page.authoring.busy import BUSY_PRESENT
from studio.page.authoring.present import PRESENT_TYPE, slideshow_overlay
from studio.page.slideshow import build_slideshow
from ui.shell.busy import busy_running

log = get_logger(__name__)


def show_start(view) -> int:
    """Where the show opens: the page on the canvas when presenting from it, else page one."""
    view = view or {}
    return int(view.get("idx", 0) or 0) if view.get("mode") == "canvas" else 0


def slideshow_for(op: str, tdoc, view):
    """What the slideshow host should hold after ``op`` ("open" or "close")."""
    if op != "open":
        return None
    tdoc = usable_tdoc(tdoc)
    if not tdoc:
        return None
    show = build_slideshow(tdoc, start=show_start(view))
    if not show.slides:
        log.info("present: the deck has no visible pages")
        return None
    return slideshow_overlay(show)


def register_present(app):
    """Wire the Present open/close callback onto ``app``."""

    @app.callback(
        Output("qs-present-host", "children"),
        Input({"type": PRESENT_TYPE, "op": ALL}, "n_clicks"),
        State("qs-tdoc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
        running=busy_running(BUSY_PRESENT),
    )
    def present(clicks, tdoc, view):
        # The pattern fires again whenever a Present or close button mounts (a top-bar
        # re-render, the show itself appearing) — only a real click counts.
        if not ctx.triggered_id or not (ctx.triggered and ctx.triggered[0].get("value")):
            return no_update
        return slideshow_for(ctx.triggered_id["op"], tdoc, view)
