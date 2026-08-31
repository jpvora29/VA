"""Create the Dash app and its page shell (stores + the app mount point).

``studio_stores`` is the half the merged application needs: every Studio store,
download and hidden sink, with no assumption about what else is on the page. The
standalone ``build_layout`` is that list plus the ``qs-app`` mount, so the two
entrypoints cannot drift apart.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html

from studio.authoring.config import ASSETS


def create_app() -> dash.Dash:
    """A Studio-only Dash app — assets, theme, and callback-exception tolerance.

    NOT the application entrypoint any more: Studio is a tab of the merged app, which
    builds its own ``dash.Dash`` in ``app.py``. This survives for tests that want
    Studio's callbacks on an app of their own (see ``tests/test_studio_dataset.py``),
    which is also why it still ignores the Chatbot's ``style.css``.
    """
    return dash.Dash(
        __name__,
        assets_folder=ASSETS,
        assets_ignore=r"^style\.css$|boardroom_dnd\.js|studio_deck\.js|typewriter\.js",
        external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
        suppress_callback_exceptions=True,
        title="QBR Studio",
    )


def studio_stores() -> list:
    """Every store, download and hidden input the Studio callbacks read or write."""
    return [
        # The view (mode/slide/tab) ALSO persists locally now — otherwise a browser
        # refresh (or Generate's post-callback reload) drops you back to Setup even
        # though the deck is still saved, which looked like "Generate did nothing".
        dcc.Store(
            id="qs-view",
            storage_type="local",
            data={
                "mode": "setup",
                "idx": 0,
                "tab": "setup",
                "lib_category": "all",
                "lib_tab": "all",
                "lib_view": "grid",
                "lib_search": "",
                "inspector_collapsed": False,
                "library_collapsed": False,
            },
        ),
        # The form selection (for Setup repopulate + regenerate) and the editable
        # document both persist locally so a refresh keeps your work.
        dcc.Store(id="qs-selection", data=None, storage_type="local"),
        dcc.Store(id="qs-doc", data=None, storage_type="local"),
        # The filled-template document — the actual deliverable in template mode.
        dcc.Store(id="qs-tdoc", data=None, storage_type="local"),
        # The active uploaded dataset — ONLY {"active": id, "rev": n}; the data
        # itself lives server-side in the dataset repository, so it survives
        # restarts without the stale-temp-file failure mode.
        dcc.Store(id="qs-dataset", data=None, storage_type="local"),
        # A digest of the option list each Setup dropdown is currently showing, so a
        # cascade re-sends only the lists that actually changed. Most filter changes move
        # two or three of the ten; shipping and re-rendering all ten every time is the
        # cost that grows with the vocabulary (see ``studio.authoring.setup``). Session
        # storage: it describes what is on screen, not the user's work.
        dcc.Store(id="qs-filter-sig", data=None, storage_type="memory"),
        dcc.Download(id="studio-pptx-download"),
        # Hidden sink: the canvas JS writes select/move/resize actions here.
        dcc.Input(id="qs-cv-sink", style={"display": "none"}),
    ]


def generating_loader() -> dcc.Loading:
    """The full-screen spinner held up while Generate assembles the deck.

    It belongs INSIDE the Studio pane, not with the stores at the root. The overlay is
    `position: fixed`, so from the root it would cover the Chatbot too — and a Generate
    you started in Studio must not block the tab you switched to. A fixed element inside
    a `display: none` pane is not painted, so scoping it here means the spinner is up
    exactly while you are looking at Studio.

    ``qs-generating`` is its child because that store is the loading trigger, and Generate
    is its sole writer — so ordinary edits never flash it.
    """
    return dcc.Loading(
        id="qs-generating-loader",
        fullscreen=True,
        type="default",
        color="#0b4bff",
        # ``qs-gen-loader`` lets the CSS turn the default solid-white fullscreen wipe
        # into a frosted-glass overlay that blurs the Setup screen behind the spinner.
        className="qs-gen-loader",
        parent_className="qs-gen-loader",
        children=dcc.Store(id="qs-generating"),
    )


def build_layout() -> html.Div:
    """The standalone page shell: the Studio stores, the spinner and the mount."""
    return html.Div([*studio_stores(), generating_loader(), html.Div(id="qs-app")])
