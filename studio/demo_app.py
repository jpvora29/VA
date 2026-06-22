"""Standalone harness for the Boardroom Studio page — wired to a real DB.

Uses the engine from ``DB_PATH``/``STUDIO_DB_PATH`` when set, otherwise a
deterministic seed DB built on first run. The page is computed end-to-end through
the real analytics primitives (no LLM, no login).

    python -m studio.demo_app   →   http://127.0.0.1:8099
"""
from __future__ import annotations

from pathlib import Path

import tempfile
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc

from studio.compute import FILTER_COLUMN, compute_overall
from studio.data import filter_options as db_filter_options
from studio.data import get_engine
from studio.deck import build_deck
from studio.export import export_deck
from studio.page.layout import studio_shell
from studio.page.sample import CUT_GROUPS
from studio.page.slide import render_deck

_ASSETS = str(Path(__file__).resolve().parent.parent / "assets")

# Default view: the subject carrier in one market, latest year.
_DEFAULTS = {"carrier": "Zurich", "country": "Singapore", "year": 2025}
_BREAKDOWNS = ["Product_Line", "SIC_Major_Class"]

engine = get_engine()

# DB-derived filter options, keyed back to the form's friendly ids.
_col_opts = db_filter_options("gpr", engine=engine)
_friendly = {fid: _col_opts.get(col, []) for fid, col in FILTER_COLUMN.items()}

# Compute → deck → PPT-like on-screen render.
_result = compute_overall(filters=_DEFAULTS, breakdowns=_BREAKDOWNS, engine=engine)


def _make_deck(report: str = "qbr"):
    return build_deck(
        _result,
        carrier=_DEFAULTS["carrier"],
        country=_DEFAULTS["country"],
        year=_DEFAULTS["year"],
        report=report,
    )


content = render_deck(_make_deck("qbr"))

app = dash.Dash(
    __name__,
    assets_folder=_ASSETS,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
)
app.layout = dash.html.Div(
    [
        studio_shell(
            content,
            cut_groups=CUT_GROUPS,
            active="overall",
            filter_options=_friendly,
            filter_values=_DEFAULTS,
            page_rail=False,
            show_footer=False,
        ),
        dcc.Download(id="studio-pptx-download"),
    ]
)


@app.callback(
    Output("studio-canvas", "children"),
    Input("studio-report-type", "value"),
    prevent_initial_call=True,
)
def _switch_report(report):
    """Rebuild the deck for the chosen report type (Full QBR vs Executive summary)."""
    return render_deck(_make_deck(report or "qbr"))


@app.callback(
    Output("studio-pptx-download", "data"),
    Input("studio-export-pptx", "n_clicks"),
    State("studio-report-type", "value"),
    prevent_initial_call=True,
)
def _export(n_clicks, report):
    """Build the deck and stream a real .pptx to the browser."""
    deck = _make_deck(report or "qbr")
    suffix = "Executive_Summary" if report == "exec" else "QBR"
    out = Path(tempfile.gettempdir()) / f"Zurich_Singapore_{suffix}.pptx"
    export_deck(deck, out_path=str(out))
    return dcc.send_file(str(out))


if __name__ == "__main__":
    app.run(debug=True, port=8099)
