"""The one navbar above every workspace: brand, the four tabs, the user chip.

The signed-in identity lives here rather than in a rail footer, because the rail
changes per tab and the identity does not — putting it in the navbar is what makes
Studio and Chatbot read as two rooms of one building instead of two buildings.
"""
from __future__ import annotations

from dash import html

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


def build_navbar(active: str, username: str) -> html.Header:
    """Brand on the left, workspace tabs in the middle, the user on the right."""
    return html.Header(
        [
            # A drawn mark, not an <img>: the old navbar pointed at
            # /assets/MarshLogo.png, which is not in the repo and rendered as a
            # broken-image glyph on every page.
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
            _user_chip(username),
        ],
        className="va-navbar",
    )
