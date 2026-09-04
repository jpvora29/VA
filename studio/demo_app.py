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
from dash import ALL, Input, Output, State, dcc, html

from studio.compute import FILTER_COLUMN, compute_overall
from studio.data import cached_filter_options, dependent_options, get_engine, peer_members
from studio.deck import build_deck
from studio.export import export_deck
from studio.page.layout import studio_shell
from studio.page.sample import CUT_GROUPS
from studio.page.slide import render_deck

_ASSETS = str(Path(__file__).resolve().parent.parent / "assets")

# Default view: the subject carrier in one market, latest year.
_DEFAULTS = {"carrier": "Zurich", "country": "Singapore", "year": 2025}
_BREAKDOWNS = ["Product_Line", "SIC_Major_Class"]

engine = get_engine()  # cheap: opens the engine, runs no query


def _friendly_options() -> dict:
    """Lazy, cached DB filter options keyed back to the form's friendly ids.

    The distinct scans (expensive on a huge table) happen here — on the boot
    callback, after first paint, behind a spinner — never at import."""
    col_opts = cached_filter_options("gpr")
    return {fid: col_opts.get(col, []) for fid, col in FILTER_COLUMN.items()}


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


def _cuts_from_states(ids, values) -> list:
    """Selected ANALYSES checkbox names (Rank/Peer/Country/…)."""
    return [i["name"] for i, v in zip(ids or [], values or []) if v]


def _peers_for(cut_names, peer_mode, custom_peers):
    """The peer set to pin: custom list when Peer comparison + Custom mode, else
    None (the engine resolves the peer group from the Peers table)."""
    if "peer_average" not in (cut_names or []):
        return None
    if peer_mode == "custom":
        return [p for p in (custom_peers or []) if p]
    return None


def _compute_and_deck(filter_values: dict, breakdowns, report: str, *, cuts=(), peers=None):
    """Recompute from the LIVE engine for the current selection, then build the deck."""
    fv = filter_values or {}
    result = compute_overall(
        filters=fv, breakdowns=(breakdowns or _BREAKDOWNS), engine=engine, peers=peers
    )
    return build_deck(
        result,
        carrier=fv.get("carrier"),
        country=fv.get("country"),
        year=fv.get("year"),
        report=report or "qbr",
        cuts=cuts,
    )


def _empty_state() -> html.Div:
    """Instant first paint — invites Generate instead of auto-running a huge query."""
    return html.Div(
        [
            html.I(className="bi bi-stars studio-empty-icon"),
            html.Div("Build your view", className="studio-empty-title"),
            html.P(
                "Choose scope, filters and breakdowns on the left, then "
                "Generate analysis. Figures are computed deterministically.",
                className="studio-empty-sub",
            ),
        ],
        className="studio-empty",
    )


app = dash.Dash(
    __name__,
    assets_folder=_ASSETS,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    # Same reason as `app.py`: Dash swaps document.title to "Updating..." for the
    # duration of every callback, which on a page this chatty reads as a flicker.
    update_title=None,
)
app.layout = html.Div(
    [
        studio_shell(
            _empty_state(),
            cut_groups=CUT_GROUPS,
            active="overall",
            filter_options={},   # lazy — populated by the boot callback after first paint
            filter_values={},
            page_rail=False,
            show_footer=False,
        ),
        dcc.Download(id="studio-pptx-download"),
    ]
)


_FLOW = "gpr"


@app.callback(
    Output({"type": "studio-filter", "col": ALL}, "options"),
    Input("studio-boot", "n_intervals"),
    Input({"type": "studio-filter", "col": "region"}, "value"),
    Input({"type": "studio-filter", "col": "country"}, "value"),
    State({"type": "studio-filter", "col": ALL}, "id"),
    prevent_initial_call=True,
)
def _load_filters(_n, region, country, ids):
    """Lazy-load filter options after first paint AND cascade them.

    One callback owns every dropdown's `options` (so there is no duplicate-output
    conflict). Country is constrained by the chosen Region; Carrier by the chosen
    Country (else Region). No `value` is set — the form starts blank, so nothing
    (no Zurich) is pre-selected; the canvas stays on its empty state until Generate."""
    base = _friendly_options()
    country_opts = dependent_options(_FLOW, "Country", {"Region": region} if region else None)
    carrier_where = {"Country": country} if country else ({"Region": region} if region else None)
    carrier_opts = dependent_options(_FLOW, "Carrier_Group", carrier_where)

    out = []
    for i in ids:
        col = i["col"]
        if col == "country":
            out.append(country_opts)
        elif col == "carrier":
            out.append(carrier_opts)
        else:
            out.append(base.get(col, []))
    return out


@app.callback(
    Output("studio-peer-custom", "options"),
    Output("studio-peer-msg", "children"),
    Input({"type": "studio-filter", "col": "carrier"}, "value"),
    Input({"type": "studio-filter", "col": "country"}, "value"),
    Input("studio-peer-mode", "value"),
    prevent_initial_call=True,
)
def _peer_panel(carrier, country, mode):
    """Populate custom-peer options and the existing-peers / no-peers message."""
    opts = dependent_options(_FLOW, "Carrier_Group", {"Country": country} if country else None)
    if mode == "custom":
        return opts, "Pick the peers to benchmark against (output shows the aggregate only)."
    if not carrier:
        return opts, "Select a carrier to see its existing peers."
    members = peer_members(_FLOW, carrier, country=country)
    if members:
        shown = ", ".join(members[:8]) + ("…" if len(members) > 8 else "")
        return opts, f"Existing peers ({len(members)}): {shown}"
    return opts, "No peers exist for this carrier — please select Custom peers."


@app.callback(
    Output("studio-canvas", "children"),
    Input("studio-generate", "n_clicks"),
    Input("studio-report-type", "value"),
    State({"type": "studio-filter", "col": ALL}, "value"),
    State({"type": "studio-filter", "col": ALL}, "id"),
    State("studio-breakdown", "value"),
    State({"type": "studio-cut", "name": ALL}, "value"),
    State({"type": "studio-cut", "name": ALL}, "id"),
    State("studio-peer-mode", "value"),
    State("studio-peer-custom", "value"),
    prevent_initial_call=True,
)
def _regenerate(n_clicks, report, filter_values, filter_ids, breakdowns,
                cut_values, cut_ids, peer_mode, custom_peers):
    """Recompute and re-render the deck for the current selection.

    Reads the filter dropdowns, the ANALYSES checkboxes (which drive the Rank/Peer
    pages), and the peer-set choice — so checking a box actually adds its page."""
    fv = _filters_from_states(filter_ids, filter_values)
    cuts = _cuts_from_states(cut_ids, cut_values)
    peers = _peers_for(cuts, peer_mode, custom_peers)
    return render_deck(_compute_and_deck(fv, breakdowns, report, cuts=cuts, peers=peers))


@app.callback(
    Output("studio-pptx-download", "data"),
    Input("studio-export-pptx", "n_clicks"),
    State("studio-report-type", "value"),
    State({"type": "studio-filter", "col": ALL}, "value"),
    State({"type": "studio-filter", "col": ALL}, "id"),
    State("studio-breakdown", "value"),
    State({"type": "studio-cut", "name": ALL}, "value"),
    State({"type": "studio-cut", "name": ALL}, "id"),
    State("studio-peer-mode", "value"),
    State("studio-peer-custom", "value"),
    prevent_initial_call=True,
)
def _export(n_clicks, report, filter_values, filter_ids, breakdowns,
            cut_values, cut_ids, peer_mode, custom_peers):
    """Build the deck for the current selection and stream a real .pptx."""
    fv = _filters_from_states(filter_ids, filter_values)
    cuts = _cuts_from_states(cut_ids, cut_values)
    peers = _peers_for(cuts, peer_mode, custom_peers)
    deck = _compute_and_deck(fv, breakdowns, report, cuts=cuts, peers=peers)
    carrier = str(fv.get("carrier", "Carrier")).replace(" ", "_")
    country = str(fv.get("country", "Market")).replace(" ", "_")
    suffix = "Executive_Summary" if report == "exec" else "QBR"
    out = Path(tempfile.gettempdir()) / f"{carrier}_{country}_{suffix}.pptx"
    export_deck(deck, out_path=str(out))
    return dcc.send_file(str(out))


if __name__ == "__main__":
    app.run(debug=True, port=8099)
