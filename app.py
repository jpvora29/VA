# Load environment (LOG_LEVEL, etc.) before any module configures logging at import time.
from dotenv import load_dotenv

load_dotenv()

import dash
from dash import html, dcc, Input, Output, State, ctx, callback_context, ALL, callback
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
        dbc.icons.FONT_AWESOME,
    ],
    suppress_callback_exceptions=True,
)


app.layout = html.Div(
    [
        # ── Global, persistent stores ───────────────────────────────────────
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
        dcc.Store(id="custom-peers-open", data=False),
        dcc.Download(id="download-pitch-report"),
        # Either the login screen or the full app shell (navbar + sidebar +
        # chat + pitch drawer), chosen by `render_app_root` off `user-store`.
        html.Div(id="app-root"),
    ]
)

from ui.callbacks import *

if __name__ == "__main__":
    # threaded=True so the poll callbacks keep being served while a streaming
    # chat turn runs in its own daemon thread (see ui/jobs.py).
    app.run(debug=True, port=8080, dev_tools_hot_reload=False, threaded=True)
