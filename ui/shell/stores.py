"""Every ``dcc.Store`` the merged application keeps alive.

All four workspaces are mounted at once and switched by visibility, so their stores
must all exist at the root — a store inside a hidden pane is still a live store, which
is exactly why an in-progress deck survives a trip to the Chatbot and back.

The Studio half is imported rather than copied (``studio.authoring.layout``), so the
merged app and the standalone Studio entrypoint cannot drift.
"""
from __future__ import annotations

from typing import Any, List

from dash import dcc

from studio.authoring.layout import studio_stores
from ui.shell.tabs import DEFAULT_TAB


def shell_stores() -> List[Any]:
    """Which workspace is on screen. Session storage, so a new tab lands on Studio."""
    return [dcc.Store(id="active-tab", data=DEFAULT_TAB, storage_type="session")]


def chat_stores() -> List[Any]:
    """The Chatbot's stores, drawers and downloads."""
    return [
        # user-store uses *session* storage: it survives a page refresh within the
        # same browser tab, but clears when the tab/window is closed — so every
        # fresh launch lands on the login page instead of silently auto-signing-in.
        dcc.Store(id="user-store", storage_type="session"),
        dcc.Store(id="active-conversation", storage_type="local"),
        dcc.Store(id="sidebar-collapsed", storage_type="local", data=False),
        dcc.Store(id="filter-store", storage_type="session"),
        dcc.Store(id="pitch-builder-open", data=False),
        dcc.Store(id="pitch-builder-store", data={}),
        dcc.Store(id="pitch-options-cache", data={}, storage_type="session"),
        # Boardroom Mode toggle: when on, the next answer renders as an inline
        # dashboard card instead of plain commentary. Memory storage (not session)
        # so every fresh launch starts in normal mode — the user opts in per visit.
        dcc.Store(id="boardroom-mode-store", data=False),
        # Editable Boardroom builder state.
        dcc.Store(id="boardroom-edit-mode", data=False),
        dcc.Store(id="boardroom-edit-target", data=None),
        dcc.Store(id="boardroom-add-target", data=None),
        # Remembers each boardroom card's current page so edits don't jump to page 0.
        dcc.Store(id="boardroom-active-page", data={}),
        # Drag-and-drop drop events from assets/boardroom_dnd.js (set_props).
        dcc.Store(id="bm-dnd", data=None),
        dcc.Store(id="custom-peers-open", data=False),
        # Decision Board: which content pane is showing (chat | board), plus the
        # currently-open detail / editor target and a counter bumped after any
        # decision mutation to force the board to repaint.
        dcc.Store(id="active-view", data="chat"),
        dcc.Store(id="decision-detail-target", data=None),
        dcc.Store(id="decision-edit-target", data=None),
        dcc.Store(id="decisions-version", data=0),
        dcc.Download(id="download-pitch-report"),
        dcc.Download(id="boardroom-download"),
    ]


def global_stores() -> List[Any]:
    """Shell + Chatbot + Studio state, in one flat list for the root layout."""
    return [*shell_stores(), *chat_stores(), *studio_stores()]
