"""The four workspaces of the application, as data.

The navbar, the pane container and the router all read this one list, so adding a
fifth workspace is a new ``Tab`` plus a pane builder — not an edit in three places.

``Tab.id`` is the value carried in the ``active-tab`` store and the suffix of the
pane's DOM id (``pane-studio``, ``pane-chat``, …), so it must stay URL-safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Tab:
    """One top-level workspace: what the navbar shows and where it routes."""

    id: str
    label: str
    icon: str
    hint: str


# Order IS the navbar order. Studio is first because it is the landing workspace.
TABS: Tuple[Tab, ...] = (
    Tab("studio", "Studio", "bi-easel2", "Build a QBR deck from the data"),
    Tab("chat", "Chatbot", "bi-chat-square-dots", "Ask the Virtual Analyst"),
    Tab("recap", "Recap", "bi-journal-text", "Summarise a period or a meeting"),
    Tab("mom", "MoM", "bi-card-checklist", "Draft minutes of meeting"),
)

DEFAULT_TAB: str = TABS[0].id

_TAB_IDS = frozenset(t.id for t in TABS)


def resolve_tab(value: str | None) -> str:
    """The tab to show for a store value — falling back to the landing tab."""
    return value if value in _TAB_IDS else DEFAULT_TAB


def pane_id(tab_id: str) -> str:
    """DOM id of the pane that hosts ``tab_id``."""
    return f"pane-{tab_id}"


def pane_class(tab_id: str, active: str) -> str:
    """The className a pane wears when ``active`` is the tab on screen.

    Hidden, not unmounted — that is what lets a half-built deck and a running chat
    turn survive a trip to another workspace and back.
    """
    return "va-pane" if tab_id == active else "va-pane va-pane-hidden"
