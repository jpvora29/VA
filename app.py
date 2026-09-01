"""ICG Virtual Analyst — the single application.

Four workspaces behind one navbar: **Studio** (build a QBR deck), **Chatbot** (ask the
analyst), **Recap** and **MoM**. They used to be two Dash apps on two ports with two
shells; they are now one app, one sign-in, one left rail and one theme.

The wiring is all this file does:

    stores + shell   ui.shell.layout.root_layout
    chat callbacks   ui.callbacks           (registered by import, via @callback)
    shell callbacks  ui.shell.router + ui.shell.collapse
    studio callbacks studio.authoring.register_*(app)
    mom callbacks    ui.mom.callbacks.register_mom

Everything else lives in the package that owns it.

    python app.py   →   http://localhost:8080
"""
# Load environment (LOG_LEVEL, DB_PATH, …) before any module configures logging or
# builds a database engine at import time — ``studio.authoring.config`` does exactly
# that, and without .env applied first it silently falls back to the seed DB.
from dotenv import load_dotenv

load_dotenv()

import dash
import dash_bootstrap_components as dbc

from studio.authoring.config import ASSETS

app = dash.Dash(
    __name__,
    assets_folder=ASSETS,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
        dbc.icons.FONT_AWESOME,
    ],
    suppress_callback_exceptions=True,
    title="ICG Virtual Analyst",
)

from ui.shell.layout import root_layout  # noqa: E402  (after `app`, by Dash convention)

app.layout = root_layout()

# Chat + boardroom + decisions register themselves through Dash's global `@callback`
# registry, which is drained when the server is set up — so the import order here does
# not matter, only that every module is imported before `run`.
from ui import callbacks as chat_callbacks  # noqa: F401,E402  (registers callbacks)
from ui.mom.callbacks import register_mom  # noqa: E402
from ui.shell.collapse import register_collapse  # noqa: E402
from ui.shell.router import register_router  # noqa: E402
from studio.authoring.data import register_data  # noqa: E402
from studio.authoring.editing import register_editing  # noqa: E402
from studio.authoring.export import register_export  # noqa: E402
from studio.authoring.navigation import register_navigation  # noqa: E402
from studio.authoring.setup import register_setup  # noqa: E402

register_router(app)       # move between the four workspaces
register_collapse(app)     # one collapse toggle width for every left rail
register_navigation(app)   # Studio: modes, slides, tabs, library panels
register_data(app)         # Studio: upload datasets, map columns, saved datasets
register_setup(app)        # Studio: Generate the deck, live scope preview
register_editing(app)      # Studio: edit fields, pages, widgets, colors on the canvas
register_export(app)       # Studio: fill/assemble the template and download the .pptx
register_mom(app)          # MoM: upload a note + deck, run the pipeline, download the .docx


if __name__ == "__main__":
    import os

    # Dual-stack bind (IPv6 + IPv4): on Windows "localhost" resolves to ::1 first, and
    # an IPv4-only socket makes every callback pay for a failed ::1 attempt. threaded
    # is on so the poll callbacks keep being served while a streaming chat turn runs in
    # its own daemon thread (ui/jobs.py). Hot reload stays off — a reload mid-Generate
    # used to reset the view to Setup so the finished deck never showed.
    from studio.serve import run_app

    run_app(
        app,
        port=int(os.environ.get("PORT", "8080")),
        debug=True,
        dev_tools_hot_reload=False,
    )
