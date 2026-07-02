"""Create the Dash app and its page shell (stores + the app mount point)."""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html

from studio.authoring.config import ASSETS


def create_app() -> dash.Dash:
    """The Dash app itself — assets, theme, and callback-exception tolerance."""
    return dash.Dash(
        __name__,
        assets_folder=ASSETS,
        assets_ignore=r"^style\.css$|boardroom_dnd\.js|studio_deck\.js|typewriter\.js",
        external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
        suppress_callback_exceptions=True,
        title="QBR Studio",
    )


def build_layout() -> html.Div:
    """The page shell: the persisted stores plus the ``qs-app`` mount the shell renders into."""
    return html.Div(
        [
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
            dcc.Download(id="studio-pptx-download"),
            # Hidden sink: the canvas JS writes select/move/resize actions here.
            dcc.Input(id="qs-cv-sink", style={"display": "none"}),
            # Full-screen spinner shown ONLY while Generate is assembling the deck
            # (it's the sole writer of ``qs-generating``, so ordinary edits don't flash it).
            dcc.Loading(
                id="qs-generating-loader",
                fullscreen=True,
                type="default",
                children=dcc.Store(id="qs-generating"),
            ),
            html.Div(id="qs-app"),
        ]
    )
