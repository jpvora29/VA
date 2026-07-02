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
            dcc.Store(
                id="qs-view",
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
            html.Div(id="qs-app"),
        ]
    )
