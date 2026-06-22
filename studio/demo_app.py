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
from dash import ALL, Input, Output, State, dcc

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


_BLANK = (None, "", [], "all", "All")


def _filters_from_states(ids, values) -> dict:
    """Map the pattern-matching filter dropdowns (id,value pairs) to a friendly
    filter dict, dropping blanks. `compute_overall` maps friendly ids → columns."""
    fv: dict = {}
    for id_, val in zip(ids or [], values or []):
        if val in _BLANK:
            continue
        fv[id_["col"]] = val
    return fv


def _compute_and_deck(filter_values: dict, breakdowns, report: str):
    """Recompute from the LIVE engine for the current selection, then build the deck."""
    fv = filter_values or _DEFAULTS
    result = compute_overall(
        filters=fv, breakdowns=(breakdowns or _BREAKDOWNS), engine=engine
    )
    return build_deck(
        result,
        carrier=fv.get("carrier"),
        country=fv.get("country"),
        year=fv.get("year"),
        report=report or "qbr",
    )


content = render_deck(_compute_and_deck(_DEFAULTS, _BREAKDOWNS, "qbr"))

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
    Input("studio-generate", "n_clicks"),
    Input("studio-report-type", "value"),
    State({"type": "studio-filter", "col": ALL}, "value"),
    State({"type": "studio-filter", "col": ALL}, "id"),
    State("studio-breakdown", "value"),
    prevent_initial_call=True,
)
def _regenerate(n_clicks, report, filter_values, filter_ids, breakdowns):
    """Recompute and re-render the deck for the current filter selection.

    Fires on "Generate analysis" and on a report-type switch; both read the live
    filter dropdowns so DB selections actually drive the analysis."""
    fv = _filters_from_states(filter_ids, filter_values)
    return render_deck(_compute_and_deck(fv, breakdowns, report))


@app.callback(
    Output("studio-pptx-download", "data"),
    Input("studio-export-pptx", "n_clicks"),
    State("studio-report-type", "value"),
    State({"type": "studio-filter", "col": ALL}, "value"),
    State({"type": "studio-filter", "col": ALL}, "id"),
    State("studio-breakdown", "value"),
    prevent_initial_call=True,
)
def _export(n_clicks, report, filter_values, filter_ids, breakdowns):
    """Build the deck for the current selection and stream a real .pptx."""
    fv = _filters_from_states(filter_ids, filter_values)
    deck = _compute_and_deck(fv, breakdowns, report)
    carrier = str(fv.get("carrier", "Carrier")).replace(" ", "_")
    country = str(fv.get("country", "Market")).replace(" ", "_")
    suffix = "Executive_Summary" if report == "exec" else "QBR"
    out = Path(tempfile.gettempdir()) / f"{carrier}_{country}_{suffix}.pptx"
    export_deck(deck, out_path=str(out))
    return dcc.send_file(str(out))


if __name__ == "__main__":
    app.run(debug=True, port=8099)
