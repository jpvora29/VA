"""Login screen and the Chatbot's left rail.

The login screen has two bodies — the SSO button where an identity provider is
configured, the original username box where none is (``core.auth.settings``) — and one
frame around them.

The rail is the shared ``va-rail`` frame (``ui.shell.rail``); collapsing is app-wide
and owned by ``ui.shell.collapse``, so nothing here knows the rail's width."""
from __future__ import annotations

from typing import Any

from dash import html
import dash_bootstrap_components as dbc

from ui.shell.rail import rail_frame, rail_section


def login_screen(error: str = "") -> html.Div:
    """The sign-in card — SSO where an identity provider is configured, else a name.

    ONE screen with two bodies rather than two screens, because everything around the
    card (the mark, the product name, the frame) is the same and the difference is which
    control signs you in. Which body is drawn is a deployment fact, not a user choice:
    if an IdP is configured there is no username box to fall back to, and if there is
    not, an SSO button would be a dead end.
    """
    from core.auth.settings import sso_enabled

    return html.Div(
        html.Div(
            [
                html.Div(html.I(className="bi bi-stars"), className="login-badge"),
                html.H1("ICG Virtual Analyst", className="login-title"),
                *(_sso_body() if sso_enabled() else _local_body()),
                html.Div(error, className="login-error", id="login-error"),
            ],
            className="login-card",
        ),
        className="login-screen",
    )


def _sso_body() -> list[Any]:
    """Sign in at the identity provider — the app never sees a credential.

    A link, not a Button with a callback: the flow is a full-page redirect to another
    origin, and a Dash callback cannot navigate one.
    """
    from core.auth.settings import LOGIN_PATH, load_settings

    settings = load_settings()
    return [
        html.P(
            f"Sign in with your {settings.provider_name} account. Your chats and "
            "preferences follow your account.",
            className="login-subtitle",
        ),
        html.A(
            [html.I(className="bi bi-shield-lock me-2"),
             html.Span(f"Sign in with {settings.provider_name}")],
            href=LOGIN_PATH,
            className="login-submit login-sso",
        ),
        # The username box has to stay on the page: `handle_login` is registered
        # unconditionally and Dash refuses a callback whose Input the app can never
        # render. Hidden rather than removed — and it signs nobody in, because the
        # gate reads the server session first (`ui.callbacks.render_app_root`).
        html.Div(_local_inputs(), className="login-local-hidden"),
    ]


def _local_body() -> list[Any]:
    """No identity provider configured: the original username-only sign-in."""
    return [
        html.P(
            "Enter a username to continue. Your chats and preferences are "
            "saved under this name.",
            className="login-subtitle",
        ),
        *_local_inputs(),
        html.Div(
            [html.I(className="bi bi-info-circle me-2"),
             html.Span("Local mode — no identity provider is configured for this "
                       "deployment, so anyone with the address can sign in as anyone.")],
            className="login-note",
        ),
    ]


def _local_inputs() -> list[Any]:
    """The username field and its button — the two components ``handle_login`` binds."""
    return [
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
    ]


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
                title=conv["title"],
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


def app_sidebar(conversations: list[dict[str, Any]] | None, username: str) -> html.Aside:
    """The Chatbot's left rail, in the shared ``va-rail`` frame.

    Same frame as Studio's mode rail, and the same collapse toggle — the width is one
    app-wide state (``ui.shell.rail``), so this builder does not need to know it. The
    signed-in user is NOT here any more: it lives once, in the navbar.
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
                    title="New chat",
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
                        title="Chats",
                    ),
                    html.Button(
                        [html.I(className="bi bi-pin-angle"), html.Span("Decision Board")],
                        id="nav-decision-board",
                        n_clicks=0,
                        className="sidebar-nav-item",
                        title="Decision Board",
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
        rail_id="chat",
        className="app-sidebar",
    )


def conversation_list_children(
    conversations: list[dict[str, Any]] | None, active_id: str | None
) -> list[Any]:
    """Just the inner items for the ``conversation-list`` container (for refreshes)."""
    conversations = conversations or []
    if not conversations:
        return [html.Div("No chats yet", className="sidebar-empty")]
    return [_conversation_item(c, active_id) for c in conversations]
