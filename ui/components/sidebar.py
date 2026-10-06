"""Login screen and the Chatbot's left rail.

The login screen has two bodies — the SSO button where an identity provider is
configured, the original username box where none is (``core.auth.settings``) — and one
frame around them.

The rail is the shared ``va-rail`` frame (``ui.shell.rail``); collapsing is app-wide
and owned by ``ui.shell.collapse``, so nothing here knows the rail's width."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from dash import dcc, html
import dash_bootstrap_components as dbc

from ui.components.chat_history import ChatGroup, ChatRow, group_conversations, row_meta
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


def _row_meta(row: ChatRow, now: datetime) -> html.Span | None:
    """"2:14 PM · Just now" under the title — when it happened, two ways.

    The time is not decoration. Every row in this list is a sentence fragment the
    user wrote themselves, and two of them ("Premium growth review", "Premium
    review") are told apart by when they happened far more often than by their
    titles.
    """
    parts = row_meta(row.when, now)
    if not parts:
        return None
    children: list[Any] = [html.Span(parts[0])]
    for part in parts[1:]:
        children += [html.Span("·", className="conv-item-dot"), html.Span(part)]
    return html.Span(children, className="conv-item-when")


def _row_menu(row: ChatRow) -> html.Div:
    """The "..." on a row: pin or unpin it, or delete it.

    Opened by a click on "..." (``assets/chat_sidebar.js`` toggles ``is-open``;
    Safari never focuses a clicked button, so a focus-driven menu never opened
    there). A click anywhere else or Escape closes it.
    """
    return html.Div(
        [
            html.Button(
                html.I(className="bi bi-three-dots"),
                className="conv-item-more",
                title="More options",
                **{"aria-label": f"More options for {row.title}"},
            ),
            html.Div(
                [
                    html.Button(
                        [html.I(className="bi bi-pin-angle"),
                         html.Span("Unpin" if row.pinned else "Pin")],
                        id={"type": "conv-pin", "id": row.id},
                        n_clicks=0,
                        className="conv-menu-item",
                    ),
                    html.Button(
                        [html.I(className="bi bi-trash"), html.Span("Delete")],
                        id={"type": "conv-del", "id": row.id},
                        n_clicks=0,
                        className="conv-menu-item conv-menu-danger",
                    ),
                ],
                className="conv-menu",
                role="menu",
            ),
        ],
        className="conv-item-actions",
        tabIndex="-1",
    )


def _conversation_item(row: ChatRow, active_id: str | None, now: datetime) -> html.Div:
    """A single sidebar row: icon, title over its time line, and a "..." menu.

    A pinned row drops the time line — it is in Pinned because WHEN no longer
    matters — and wears a pin instead of a speech bubble.
    """
    state = (" conv-item-active" if row.id == active_id else "") + (
        " conv-item-pinned" if row.pinned else "")
    icon = "bi bi-pin-angle" if row.pinned else "bi bi-chat-left-text"
    return html.Div(
        [
            html.Button(
                [
                    html.I(className=f"{icon} conv-item-icon"),
                    html.Span(
                        [
                            html.Span(row.title, className="conv-item-title"),
                            None if row.pinned else _row_meta(row, now),
                        ],
                        className="conv-item-text",
                    ),
                ],
                id={"type": "conv-item", "id": row.id},
                n_clicks=0,
                className="conv-item-open",
                title=row.title,
            ),
            _row_menu(row),
        ],
        className="conv-item" + state,
        **{"data-title": row.title.lower()},
    )


def _group_block(group: ChatGroup, active_id: str | None, now: datetime) -> html.Div:
    """One labelled group — "TODAY  OCT 6, 2026" over its rows."""
    head = [html.Span(group.label, className="conv-group-name")]
    if group.date_label:
        head.append(html.Span(group.date_label, className="conv-group-date"))
    return html.Div(
        [
            html.Div(head, className="conv-group-label"),
            *[_conversation_item(row, active_id, now) for row in group.rows],
        ],
        className="conv-group" + (" conv-group-pinned" if group.key == "pinned" else ""),
    )


def _search_box() -> html.Div:
    """Filters the list as you type; Ctrl K gets here from anywhere in the chat.

    Filtering is in the browser (assets/chat_sidebar.js): it is a substring match
    over titles already on the page, and a server round trip per keystroke would
    only add latency to it. (Dash 3's ``dcc.Input`` puts className on a wrapper
    around the field; va_shell.css styles the inner ``input``.)
    """
    return html.Div(
        [
            html.I(className="bi bi-search conv-search-icon"),
            dcc.Input(
                id="conv-search",
                type="search",
                placeholder="Search conversations",
                autoComplete="off",
                className="conv-search-input",
            ),
            html.Kbd("Ctrl K", className="conv-search-kbd"),
        ],
        className="conv-search",
    )


def _shortcut(keys: str, text: str) -> html.Div:
    """One line of the shortcuts card."""
    return html.Div([html.Span(text), html.Kbd(keys)], className="help-shortcut")


def _help_footer() -> html.Div:
    """"Help & shortcuts" — the keys that make the chat fast, and the tour.

    A focus-opened card, like the row menus. The tour button forwards its click
    to the navbar's (``data-click``), so the tour keeps one entry point.
    """
    return html.Div(
        [
            html.Button(
                [html.I(className="bi bi-question-circle"),
                 html.Span("Help & shortcuts", className="help-label"),
                 html.I(className="bi bi-chevron-right help-chevron")],
                className="help-toggle",
                title="Help & shortcuts",
            ),
            html.Div(
                [
                    html.Div("Keyboard shortcuts", className="help-card-title"),
                    _shortcut("Ctrl K", "Search conversations"),
                    _shortcut("Shift Esc", "Focus the question box"),
                    _shortcut("Enter", "Send"),
                    _shortcut("Shift Enter", "New line"),
                    _shortcut("/", "Commands"),
                    _shortcut("Esc", "Stop a running answer"),
                    html.Button(
                        [html.I(className="bi bi-compass"), html.Span("Take the tour")],
                        className="help-tour",
                        **{"data-click": "tour-open"},
                    ),
                ],
                className="help-card",
            ),
        ],
        className="sidebar-help",
        tabIndex="-1",
    )


def app_sidebar(conversations: list[dict[str, Any]] | None, username: str) -> html.Aside:
    """The Chatbot's left rail, in the shared ``va-rail`` frame.

    Same frame as Studio's mode rail, and the same collapse toggle — the width is one
    app-wide state (``ui.shell.rail``), so this builder does not need to know it. The
    signed-in user is NOT here any more: it lives once, in the navbar.
    """
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
            _search_box(),
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
                        # Not a pin: that icon means a pinned CHAT in this rail,
                        # and two meanings for one icon read as a broken pin.
                        [html.I(className="bi bi-kanban"), html.Span("Decision Board")],
                        id="nav-decision-board",
                        n_clicks=0,
                        className="sidebar-nav-item",
                        title="Decision Board",
                    ),
                ],
            ),
            html.Div(
                conversation_list_children(conversations, None),
                id="conversation-list",
                className="conversation-list",
            ),
            html.Div("No chats match your search", className="conv-search-empty"),
        ],
        rail_id="chat",
        footer=_help_footer(),
        className="app-sidebar",
    )


def conversation_list_children(
    conversations: list[dict[str, Any]] | None,
    active_id: str | None,
    now: datetime | None = None,
) -> list[Any]:
    """The grouped rows inside the ``conversation-list`` container (for refreshes)."""
    if not conversations:
        return [html.Div("No chats yet", className="sidebar-empty")]
    now = now or datetime.now()
    return [_group_block(group, active_id, now)
            for group in group_conversations(conversations, now)]
