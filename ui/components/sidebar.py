"""Login screen and the left, collapsible Claude-style chat sidebar."""
from __future__ import annotations

from typing import Any

from dash import html, dcc
import dash_bootstrap_components as dbc

from ui.shell.rail import RAIL_CLASS, rail_frame, rail_section


# What the chat rail adds on top of the shared rail class, open and collapsed.
_OPEN = "app-sidebar"
_COLLAPSED = "app-sidebar app-sidebar-collapsed"


def sidebar_class(collapsed: bool) -> str:
    """The chat rail's FULL className, shared class included.

    The collapse toggle is a clientside callback that REPLACES this attribute, so it
    has to rebuild the whole string. It and the initial render both derive it here,
    so a rename of the shared rail class cannot break the toggle.
    """
    return f"{RAIL_CLASS} {_COLLAPSED if collapsed else _OPEN}"


def login_screen() -> html.Div:
    """Centered username-only sign-in card (no passwords by design)."""
    return html.Div(
        html.Div(
            [
                html.Div(html.I(className="bi bi-stars"), className="login-badge"),
                html.H1("ICG Virtual Analyst", className="login-title"),
                html.P(
                    "Enter a username to continue. Your chats and preferences are "
                    "saved under this name.",
                    className="login-subtitle",
                ),
                dbc.Input(
                    id="login-username",
                    placeholder="Your name",
                    debounce=True,
                    autoFocus=True,
                    className="login-input",
                ),
                dbc.Button(
                    [html.Span("Continue"), html.I(className="bi bi-arrow-right ms-2")],
                    id="login-submit",
                    n_clicks=0,
                    className="login-submit",
                ),
                html.Div(id="login-error", className="login-error"),
            ],
            className="login-card",
        ),
        className="login-screen",
    )


def _conversation_item(conv: dict[str, Any], active_id: str | None) -> html.Div:
    """A single sidebar row: open button + hover delete."""
    conv_id = conv["id"]
    is_active = conv_id == active_id
    return html.Div(
        [
            html.Button(
                [
                    html.I(className="bi bi-chat-left-text conv-item-icon"),
                    html.Span(conv["title"], className="conv-item-title"),
                ],
                id={"type": "conv-item", "id": conv_id},
                n_clicks=0,
                className="conv-item-open",
            ),
            html.Button(
                html.I(className="bi bi-trash"),
                id={"type": "conv-del", "id": conv_id},
                n_clicks=0,
                className="conv-item-del",
                title="Delete chat",
            ),
        ],
        className="conv-item" + (" conv-item-active" if is_active else ""),
    )


def app_sidebar(
    conversations: list[dict[str, Any]] | None,
    username: str,
    collapsed: bool = False,
) -> html.Aside:
    """The Chatbot's left rail, in the shared ``va-rail`` frame.

    Same frame as Studio's mode rail so the left edge of the app does not change
    identity when you switch tabs. The signed-in user is NOT here any more — it lives
    once, in the navbar, because it is the same on every tab.
    """
    conversations = conversations or []
    return rail_frame(
        "Chatbot",
        [
            html.Div(
                dbc.Button(
                    [html.I(className="bi bi-pencil-square"), html.Span("New chat")],
                    id="new-chat-btn",
                    n_clicks=0,
                    className="new-chat-btn",
                ),
                className="sidebar-top",
            ),
            rail_section(
                None,
                [
                    html.Button(
                        [html.I(className="bi bi-chat-left-text"), html.Span("Chats")],
                        id="nav-chat-view",
                        n_clicks=0,
                        className="sidebar-nav-item",
                    ),
                    html.Button(
                        [html.I(className="bi bi-pin-angle"), html.Span("Decision Board")],
                        id="nav-decision-board",
                        n_clicks=0,
                        className="sidebar-nav-item",
                    ),
                ],
            ),
            html.Div("Recent", className="va-rail-label"),
            html.Div(
                (
                    [_conversation_item(c, None) for c in conversations]
                    if conversations
                    else [html.Div("No chats yet", className="sidebar-empty")]
                ),
                id="conversation-list",
                className="conversation-list",
            ),
        ],
        action=dbc.Button(
            html.I(className="bi bi-layout-sidebar"),
            id="sidebar-collapse-btn",
            n_clicks=0,
            className="sidebar-collapse-btn",
            title="Collapse sidebar",
        ),
        className=_COLLAPSED if collapsed else _OPEN,
        id="app-sidebar",
    )


def conversation_list_children(
    conversations: list[dict[str, Any]] | None, active_id: str | None
) -> list[Any]:
    """Just the inner items for the ``conversation-list`` container (for refreshes)."""
    conversations = conversations or []
    if not conversations:
        return [html.Div("No chats yet", className="sidebar-empty")]
    return [_conversation_item(c, active_id) for c in conversations]
