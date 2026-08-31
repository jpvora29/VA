"""One builder per workspace, plus the dispatch table the shell renders from.

Every builder has the same shape — ``(user_id, username) -> Component`` — so the shell
can build all four without knowing anything about any of them. Each returns the *inside*
of a pane: a ``va-rail`` and a content host. The pane wrapper itself is added by
``build_panes``, so the four are structurally identical and the router only has to
toggle a class.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from dash import html

from core.memory.suggestions import generate_starter_questions
from core.store.conversations import list_conversations
from studio.authoring.layout import generating_loader

from ui.components.chatbot import chatbot_page
from ui.components.sidebar import app_sidebar
from ui.decisions.render import decision_board_view
from ui.mom.render import mom_body, mom_rail
from ui.recap.render import recap_body, recap_rail
from ui.shell.tabs import TABS, pane_class, pane_id


def _studio_pane(user_id: int, username: str) -> Any:
    """Studio renders itself: ``studio.authoring.navigation`` fills ``qs-app``
    with the whole ``qs-root`` (its rail + top bar + canvas).

    The Generate spinner is mounted here rather than at the root so it cannot cover
    another workspace — see ``studio.authoring.layout.generating_loader``.
    """
    return html.Div(
        [generating_loader(), html.Div(id="qs-app", className="va-pane-full")],
        className="va-pane-full",
    )


def _chat_pane(user_id: int, username: str) -> Any:
    """Chat rail + the two content views (chat / decision board) it switches between."""
    conversations = list_conversations(user_id)
    starters = generate_starter_questions(user_id)
    return html.Div(
        [
            app_sidebar(conversations, username, collapsed=False),
            html.Div(
                html.Div(
                    [
                        # Both views stay mounted; the view-router callback toggles
                        # visibility so the chat keeps its DOM and stores on switch.
                        html.Div(
                            chatbot_page(username, starters),
                            id="view-chat",
                            className="view-pane",
                        ),
                        html.Div(
                            decision_board_view(),
                            id="view-board",
                            className="view-pane view-hidden",
                        ),
                    ],
                    id="main-content",
                    className="main-content",
                ),
                className="main-container",
            ),
        ],
        className="va-pane-split",
    )


def _recap_pane(user_id: int, username: str) -> Any:
    return html.Div([recap_rail(), html.Div(recap_body(), className="main-container")],
                    className="va-pane-split")


def _mom_pane(user_id: int, username: str) -> Any:
    return html.Div([mom_rail(), html.Div(mom_body(), className="main-container")],
                    className="va-pane-split")


PaneBuilder = Callable[[int, str], Any]

# One entry per tab in ``ui.shell.tabs.TABS`` — the shell asserts they line up.
PANE_BUILDERS: Dict[str, PaneBuilder] = {
    "studio": _studio_pane,
    "chat": _chat_pane,
    "recap": _recap_pane,
    "mom": _mom_pane,
}


def build_panes(user_id: int, username: str, active: str) -> List[Any]:
    """All four workspaces, mounted at once, with only the active one visible."""
    return [
        html.Div(
            PANE_BUILDERS[tab.id](user_id, username),
            id=pane_id(tab.id),
            className=pane_class(tab.id, active),
        )
        for tab in TABS
    ]
