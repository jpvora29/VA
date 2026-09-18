"""The one navbar above every workspace: brand, the four tabs, the user chip.

The signed-in identity lives here rather than in a rail footer, because the rail
changes per tab and the identity does not — putting it in the navbar is what makes
Studio and Chatbot read as two rooms of one building instead of two buildings.
"""
from __future__ import annotations

from dash import html

from ui.components.tour import tour_button
from ui.shell.tabs import TABS, Tab


def _tab_button(tab: Tab, active: str) -> html.Button:
    is_active = tab.id == active
    return html.Button(
        [
            html.I(className=f"bi {tab.icon}"),
            html.Span(tab.label, className="va-tab-label"),
        ],
        id={"type": "va-tab", "tab": tab.id},
        n_clicks=0,
        title=tab.hint,
        className="va-tab" + (" va-tab-active" if is_active else ""),
    )


def tab_class(tab_id: str, active: str) -> str:
    """The className a tab button should carry for ``active`` — used by the router."""
    return "va-tab" + (" va-tab-active" if tab_id == active else "")


def _user_chip(username: str) -> html.Div:
    initial = (username or "?").strip()[:1].upper() or "?"
    return html.Div(
        [
            html.Div(initial, className="va-user-avatar"),
            html.Span(username, className="va-user-name"),
            html.Button(
                html.I(className="bi bi-box-arrow-right"),
                id="logout-btn",
                n_clicks=0,
                className="va-logout-btn",
                title="Log out",
            ),
        ],
        className="va-user-chip",
    )


def _model_chip() -> html.Div:
    """Which model is answering, named beside the identity.

    Small and quiet: a reader who has just been given an answer should be able to
    see what wrote it without opening a drawer, and a reviewer comparing two runs
    needs to know whether the model moved under them. Empty when nothing is
    configured — a chip reading "(not configured)" tells a user nothing they can
    act on, and the startup banner already says it where it can be fixed.
    """
    try:
        from core.llm.clients import primary_model

        model = primary_model()
    except Exception:  # noqa: BLE001 - the navbar renders with or without a model
        model = ""
    if not model:
        return html.Div(className="va-model-chip", hidden=True)
    return html.Div(
        [html.I(className="bi bi-cpu"), html.Span(model, className="va-model-name")],
        className="va-model-chip",
        title=f"Answers on this page are written by {model}",
    )


def build_navbar(active: str, username: str) -> html.Header:
    """Brand on the left, workspace tabs in the middle, the user on the right."""
    return html.Header(
        [
            # A drawn mark, not an <img>: the old navbar pointed at
            # /assets/MarshLogo.png, which is not in the repo and rendered as a
            # broken-image glyph on every page.
            # Below the drawer breakpoint the rail slides off-screen, taking its
            # own collapse toggle with it. This is the way back in. It carries the
            # SAME pattern id as every rail toggle, so it needs no wiring of its
            # own (see ui.shell.collapse).
            html.Button(
                html.I(className="bi bi-list"),
                id={"type": "va-rail-toggle", "rail": "navbar"},
                n_clicks=0,
                className="va-rail-open",
                title="Show the sidebar",
            ),
            html.Div(
                [
                    html.Div("VA", className="va-brand-mark"),
                    html.Span("ICG Virtual Analyst", className="va-brand-name"),
                ],
                className="va-brand",
            ),
            html.Nav(
                [_tab_button(t, active) for t in TABS],
                className="va-tabs",
            ),
            # The way in for someone who has just been handed the app. It sits
            # beside the identity rather than inside a workspace, because it is
            # about the whole product, not about the tab you happen to be on.
            html.Div(
                [_model_chip(), tour_button(), _user_chip(username)],
                className="va-navbar-end",
            ),
        ],
        className="va-navbar",
    )
