# Load environment (LOG_LEVEL, etc.) before any module configures logging at import time.
from dotenv import load_dotenv

load_dotenv()

import dash
from dash import html, dcc, Input, Output, State, ctx, callback_context, ALL, callback
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from ui.components.navbar import build_navbar
from ui.components.chatbot import pitch_builder_drawer

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
        dbc.icons.FONT_AWESOME,
    ],
    suppress_callback_exceptions=True,
)


navbar = build_navbar()

app.layout = html.Div(
    [
        dcc.Store(id="filter-store", storage_type="session"),
        dcc.Store(id="pitch-builder-open", data=False),
        dcc.Store(id="pitch-builder-store", data={}),
        dcc.Store(id="pitch-options-cache", data={}, storage_type="session"),
        dcc.Download(id="download-pitch-report"),
        # Navbar
        navbar,
        # Body Section
        html.Div(
            [
                # Main Content
                html.Div(id="main-content", className="main-content")
            ],
            className="main-container",
        ),
        pitch_builder_drawer(),
    ]
)

from ui.callbacks import *

if __name__ == "__main__":
    app.run(debug=True, port=8080, dev_tools_hot_reload=False)
