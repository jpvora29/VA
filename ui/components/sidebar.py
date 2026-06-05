"""Login screen and the left, collapsible Claude-style chat sidebar."""
from __future__ import annotations

from typing import Any

from dash import html, dcc
import dash_bootstrap_components as dbc


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
) -> html.Div:
    """Left rail: New chat, conversation history, and the user footer."""
    conversations = conversations or []
    initial = (username or "?").strip()[:1].upper() or "?"

    return html.Div(
        [
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="bi bi-pencil-square"), html.Span("New chat")],
                        id="new-chat-btn",
                        n_clicks=0,
                        className="new-chat-btn",
                    ),
                    dbc.Button(
                        html.I(className="bi bi-layout-sidebar"),
                        id="sidebar-collapse-btn",
                        n_clicks=0,
                        className="sidebar-collapse-btn",
                        title="Collapse sidebar",
                    ),
                ],
                className="sidebar-top",
            ),
            html.Div("Recent", className="sidebar-section-label"),
            html.Div(
                (
                    [_conversation_item(c, None) for c in conversations]
                    if conversations
                    else [html.Div("No chats yet", className="sidebar-empty")]
                ),
                id="conversation-list",
                className="conversation-list",
            ),
            html.Div(
                [
                    html.Div(initial, className="user-avatar"),
                    html.Span(username, className="user-name"),
                    dbc.Button(
                        html.I(className="bi bi-box-arrow-right"),
                        id="logout-btn",
                        n_clicks=0,
                        className="logout-btn",
                        title="Log out",
                    ),
                ],
                className="sidebar-footer",
            ),
        ],
        id="app-sidebar",
        className="app-sidebar" + (" app-sidebar-collapsed" if collapsed else ""),
    )


def conversation_list_children(
    conversations: list[dict[str, Any]] | None, active_id: str | None
) -> list[Any]:
    """Just the inner items for the ``conversation-list`` container (for refreshes)."""
    conversations = conversations or []
    if not conversations:
        return [html.Div("No chats yet", className="sidebar-empty")]
    return [_conversation_item(c, active_id) for c in conversations]
