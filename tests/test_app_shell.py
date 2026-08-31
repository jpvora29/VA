"""The merged application shell: one navbar, four workspaces, one page.

Studio and the Chatbot used to be two Dash apps on two ports. Merging them put every
component from both onto ONE page, and that is where the integration risks live:

  * two components claiming the same id (Dash raises, the whole app dies),
  * a callback pointing at an id that no longer exists,
  * a pane switch that unmounts work in progress,
  * a workspace that assumes it owns the viewport.

The first half of this file tests the frame with nothing but Dash. The second half
builds the real, fully wired application — it needs the ``config`` package, which is
absent from some working copies, so it skips rather than fails there.
"""
from __future__ import annotations

import collections
import json

import pytest
from dash.development.base_component import Component

from ui.shell.navbar import build_navbar, tab_class
from ui.shell.placeholder import placeholder_body, placeholder_rail
from ui.shell.rail import RAIL_CLASS, rail_frame, rail_section
from ui.shell.tabs import DEFAULT_TAB, TABS, pane_class, pane_id, resolve_tab


# ── helpers ──────────────────────────────────────────────────────────────────


def _walk(node):
    """Every component in a tree, whether it is nested in lists or in children."""
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk(item)


def _ids(node) -> list[str]:
    """Component ids as comparable strings (a dict id becomes its canonical JSON)."""
    out = []
    for component in _walk(node):
        cid = getattr(component, "id", None)
        if cid is None:
            continue
        out.append(json.dumps(cid, sort_keys=True) if isinstance(cid, dict) else cid)
    return out


def _classes(node, prefix: str) -> dict[str, str]:
    return {
        c.id: (c.className or "")
        for c in _walk(node)
        if isinstance(getattr(c, "id", None), str) and c.id.startswith(prefix)
    }


# ── the frame ────────────────────────────────────────────────────────────────


def test_studio_is_the_landing_workspace():
    """The user lands on Studio; Chatbot, Recap and MoM follow, in that order."""
    assert [t.id for t in TABS] == ["studio", "chat", "recap", "mom"]
    assert DEFAULT_TAB == "studio"


@pytest.mark.parametrize("value", [None, "", "bogus", "Studio", 7])
def test_an_unknown_tab_falls_back_to_the_landing_workspace(value):
    """A stale or hand-edited ``active-tab`` must not render an empty application."""
    assert resolve_tab(value) == DEFAULT_TAB


def test_exactly_one_pane_is_visible_for_any_tab():
    for tab in TABS:
        visible = [t.id for t in TABS if "va-pane-hidden" not in pane_class(t.id, tab.id)]
        assert visible == [tab.id]


def test_a_hidden_pane_is_hidden_not_unmounted():
    """Visibility, not unmounting — that is what lets a half-built deck and an
    unsent message survive a trip to another workspace and back."""
    hidden = pane_class("chat", "studio")
    assert hidden.startswith("va-pane")
    assert "va-pane-hidden" in hidden


def test_the_navbar_lights_exactly_one_tab():
    navbar = build_navbar("recap", "Jash")
    active = [
        c for c in _walk(navbar)
        if isinstance(getattr(c, "id", None), dict)
        and c.id.get("type") == "va-tab"
        and "va-tab-active" in (c.className or "")
    ]
    assert [c.id["tab"] for c in active] == ["recap"]
    assert tab_class("recap", "recap") != tab_class("chat", "recap")


def test_the_navbar_carries_the_one_sign_out_control():
    """Sign-out moved from the chat rail to the navbar; there must be exactly one,
    or Dash refuses the ``logout-btn`` callback for a duplicate id."""
    assert _ids(build_navbar("studio", "Jash")).count("logout-btn") == 1


def test_every_rail_wears_the_shared_frame():
    """Studio's rail, the Chatbot's rail and the placeholders are one component."""
    from studio.page.authoring.chrome import mode_rail

    rails = [
        mode_rail("setup", {"total": 12}),
        placeholder_rail("Recap", ("One", "Two")),
        rail_frame("Anything", [rail_section("Group", [])]),
    ]
    for rail in rails:
        assert rail.className.split()[0] == RAIL_CLASS


def test_the_studio_rail_keeps_its_pattern_ids_after_the_restyle():
    """Re-dressing the rail must not change the ids its callbacks are bound to."""
    from studio.page.authoring.chrome import mode_rail
    from studio.page.authoring.constants import MODES

    ids = _ids(mode_rail("canvas", {"total": 3}))
    for mode in MODES:
        assert json.dumps({"mode": mode["id"], "type": "qs-mode"}, sort_keys=True) in ids


def test_the_shell_stylesheet_still_loads_last():
    """`va_shell.css` overrides the navy rail and the full-viewport heights the two
    apps declared when each owned the page. Dash serves /assets sorted, so a new
    stylesheet sorting after it would silently take the chrome back."""
    import os

    sheets = sorted(f for f in os.listdir("assets") if f.endswith(".css"))
    assert sheets[-1] == "va_shell.css", sheets


def test_a_placeholder_workspace_renders_without_a_backend():
    """Recap and MoM have no engine yet and must still render a real workspace."""
    from ui.mom.render import mom_body, mom_rail
    from ui.recap.render import recap_body, recap_rail

    for rail, body in ((recap_rail(), recap_body()), (mom_rail(), mom_body())):
        assert RAIL_CLASS in rail.className
        assert list(_walk(body))  # a body, not an empty div
    assert placeholder_body(icon="bi-x", title="T", blurb="B", bullets=()) is not None


# ── the wired application ────────────────────────────────────────────────────

# The Chatbot half imports ``document_builder`` -> ``config.report_config``. Some
# working copies do not have ``config/`` at all, so the tests that need the WIRED
# application skip themselves through these fixtures — rather than a module-level
# skip, which would take the frame tests above with it.
_NEEDS_CONFIG = "config/ is absent from this working copy; the Chatbot half cannot import"


@pytest.fixture(scope="module")
def merged_app():
    pytest.importorskip("config.report_config", reason=_NEEDS_CONFIG)
    import app as app_module

    # The Chatbot registers through Dash's GLOBAL `@callback` registry, which Dash
    # only drains into ``callback_map`` when it sets the server up — on the first
    # request. Doing it here is what makes this fixture the real, wired application
    # rather than half of it, and it runs Dash's own layout validation on the way.
    app_module.app._setup_server()
    return app_module.app


@pytest.fixture(scope="module")
def shells():
    pytest.importorskip("config.report_config", reason=_NEEDS_CONFIG)
    from ui.shell.layout import app_shell

    return {t.id: app_shell(1, "Tester", t.id) for t in TABS}


def test_the_whole_page_has_no_duplicate_component_ids(merged_app, shells):
    """The single biggest merge risk: Dash refuses to start on a duplicate id."""
    seen = collections.Counter(_ids([merged_app.layout, shells["studio"]]))
    assert [i for i, n in seen.items() if n > 1] == []


def test_studio_bodies_do_not_collide_with_the_shell(merged_app, shells):
    """Studio fills ``qs-app`` from a callback, so its bodies land on the page
    after the shell does — they must not clash with anything already there."""
    from studio.page import authoring as A
    from studio.page.sample import CUT_GROUPS

    on_page = set(_ids([merged_app.layout, shells["studio"]]))
    for mode in ("setup", "data", "canvas", "review"):
        body = A.authoring_shell(
            None, mode=mode, view={"idx": 0, "tab": "setup"}, cut_groups=CUT_GROUPS
        )
        assert sorted(set(_ids(body)) & on_page) == []


def test_the_shell_mounts_all_four_workspaces_and_shows_one(shells):
    for tab in TABS:
        panes = _classes(shells[tab.id], "pane-")
        assert set(panes) == {pane_id(t.id) for t in TABS}
        visible = [k for k, v in panes.items() if "va-pane-hidden" not in v]
        assert visible == [pane_id(tab.id)]


def test_both_halves_registered_their_callbacks(merged_app):
    """The end-to-end wiring: shell routing, the Chatbot, and every Studio group."""
    keys = " ".join(merged_app.callback_map)
    assert "pane-studio.className" in keys      # shell router
    assert "app-root.children" in keys          # login gate
    assert "qs-app.children" in keys            # Studio render
    assert "studio-pptx-download" in keys       # Studio export
    assert "chat-box" in keys                   # Chatbot turn


def test_no_callback_points_at_a_component_the_app_can_never_render(merged_app, shells):
    """Every fixed-id Input/State must exist somewhere the app actually renders:
    the root layout, one of the four panes, or a Studio body."""
    from studio.page import authoring as A
    from studio.page.sample import CUT_GROUPS

    from ui.components.sidebar import login_screen

    # `app-root` renders EITHER the sign-in card or the signed-in shell, so both
    # count as places the app can render.
    known = set(_ids([merged_app.layout, login_screen(), *shells.values()]))
    for mode in ("setup", "data", "canvas", "review"):
        known |= set(_ids(A.authoring_shell(
            None, mode=mode, view={"idx": 0, "tab": "setup"}, cut_groups=CUT_GROUPS)))

    # Chat and boardroom bodies are rendered into `chat-box` by their own callbacks,
    # so restrict the assertion to the ids this integration is responsible for.
    shell_owned = {
        "active-tab", "app-root", "app-sidebar", "logout-btn", "qs-app",
        "new-chat-btn", "sidebar-collapse-btn", "nav-chat-view", "nav-decision-board",
        "conversation-list", "login-submit", "login-username",
    }
    for key, callback in merged_app.callback_map.items():
        for dep in list(callback["inputs"]) + list(callback["state"]):
            if isinstance(dep["id"], str) and dep["id"] in shell_owned:
                assert dep["id"] in known, f"{key} -> {dep['id']}"


def test_the_generate_spinner_cannot_cover_another_workspace(merged_app, shells):
    """Studio's spinner is `position: fixed`. At the root it would black out the
    Chatbot while a deck generates; inside the (display:none) Studio pane it is
    painted only while you are looking at Studio."""
    assert "qs-generating" not in _ids(merged_app.layout)
    studio_pane = next(
        c for c in _walk(shells["studio"])
        if getattr(c, "id", None) == pane_id("studio")
    )
    assert "qs-generating" in _ids(studio_pane)


def test_the_page_serialises_the_way_dash_ships_it(merged_app, shells):
    import plotly.utils

    for tree in (merged_app.layout, shells["chat"], shells["mom"]):
        json.dumps(tree.to_plotly_json(), cls=plotly.utils.PlotlyJSONEncoder)
