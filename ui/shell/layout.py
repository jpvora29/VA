"""The application shell: one navbar, four panes, and the modals they share.

``root_layout`` is what ``app.py`` assigns. It is deliberately thin — every store, then
a single ``app-root`` div that the login gate fills with either the sign-in card or
``app_shell``. Nothing above ``app-root`` depends on who is signed in, which is why the
Studio stores survive a logout.
"""
from __future__ import annotations

from dash import html

from ui.boardroom.editor import all_modals as boardroom_modals
from ui.components.chatbot import custom_peers_modal, pitch_builder_drawer
from ui.decisions.render import decision_modals
from ui.shell.navbar import build_navbar
from ui.shell.panes import PANE_BUILDERS, build_panes
from ui.shell.rail import rails_class
from ui.shell.stores import global_stores
from ui.shell.tabs import TABS

# A tab without a pane builder would render an empty workspace and no error, so the
# two lists are checked once, at import.
assert {t.id for t in TABS} == set(PANE_BUILDERS), "every tab needs a pane builder"


def app_shell(
    user_id: int, username: str, active_tab: str, rails_collapsed: bool = True
) -> html.Div:
    """Signed-in layout: navbar, the four workspaces, and the app-wide overlays."""
    return html.Div(
        [
            build_navbar(active_tab, username),
            # `va-body` also carries the rail width, because collapsing is app-wide
            # rather than per-tab (see ``ui.shell.rail``).
            html.Div(
                build_panes(user_id, username, active_tab),
                id="va-body",
                className=rails_class(rails_collapsed),
            ),
            # Overlays live outside the panes: they are positioned against the
            # viewport, and a pane that is display:none would take them with it.
            pitch_builder_drawer(),
            custom_peers_modal(),
            boardroom_modals(),
            decision_modals(),
        ],
        className="va-app",
    )


def root_layout() -> html.Div:
    """The whole page: global state, then the login-gated shell mount."""
    return html.Div([*global_stores(), html.Div(id="app-root")])


__all__ = ["app_shell", "root_layout"]
