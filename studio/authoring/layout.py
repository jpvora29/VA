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

# How often the Generate poll asks a running build how it is doing. A build is minutes
# long, so a fast tick buys nothing but callback traffic; a slow one makes the finished
# deck feel late.
GEN_POLL_MS = 1500


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
        # The deck build in flight, and the tick that follows it. A build takes minutes,
        # so Generate starts a ``studio.authoring.jobs.DeckJob`` and this poll collects
        # the result — a callback that held the request open that long lost its answer
        # and left the previous deck on screen. Memory storage: a reload has no thread
        # left to resume, so remembering a job id would only lie to the user.
        dcc.Store(id="qs-gen-job", data=None, storage_type="memory"),
        dcc.Interval(id="qs-gen-poll", interval=GEN_POLL_MS, n_intervals=0, disabled=True),
        dcc.Download(id="studio-pptx-download"),
        # Hidden sink: the canvas JS writes select/move/resize actions here.
        dcc.Input(id="qs-cv-sink", style={"display": "none"}),
    ]


def generating_loader() -> dcc.Loading:
    """The full-screen spinner held up while Generate STARTS a build.

    It no longer covers the build itself: that runs in a background thread now
    (``studio.authoring.jobs``) and is followed by the Setup progress panel, which can say
    which phase a ten-minute assembly is in where a spinner could only say "something".
    What is left for this to cover is the moment between the click and the first progress
    paint — the form validation, the peer checks, the dataset gate.

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


def generate_progress_host() -> html.Div:
    """Where a running build reports itself — mounted for as long as Studio is.

    Deliberately NOT inside the Setup form. A build takes minutes and the author may walk
    the previous deck's canvas while it runs, and the poll that fills this writes into it
    every tick: an output that only exists on one screen would break the poll the moment
    they navigated away from that screen. Here it survives every mode switch, and floats
    over whichever one is open.
    """
    return html.Div(id="studio-gen-progress", className="qs-gen-host")


def studio_chrome() -> list:
    """The pane-scoped overlays: the start spinner and the build's progress card."""
    return [generating_loader(), generate_progress_host()]


def build_layout() -> html.Div:
    """The standalone page shell: the Studio stores, the overlays and the mount."""
    return html.Div([*studio_stores(), *studio_chrome(), html.Div(id="qs-app")])
