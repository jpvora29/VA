"""Render a turn's evidence as ONE panel the reader moves around in.

Three plots stacked under an answer is three things to scroll past. One panel
with a tab per result set is one thing to look at, and the reader chooses which
cut they want — the difference between an answer you read and an answer you use.

Structure, per panel:

    [ Premium | Broker survey ]              <- view tabs (only when >1 view)
    [ Chart | Data ]                         <- per view, only when it has a chart
    <figure or table>

Every view keeps its own Chart/Data switch, reusing the pattern-matching ids the
existing toggle callback already drives (`chart-toggle-*` / `chart-fig` /
`chart-table` on a unique `idx`). The only new callback is the tab switch.

A view with no chart renders its table directly: the rows ARE the evidence, and
an answer that produced numbers should never show nothing.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from dash import dash_table, dcc, html

from core.analytics.positioning import DOWN, UP
from ui.evidence import EvidenceView

#: The header's ground. Brand navy, so the table reads as part of the product
#: rather than as a default grid dropped into it.
_HEADER_INK = "#FFFFFF"
_HEADER_BG = "#000F47"

#: Body text. Black at 12px Arial — a table is reference material, and the
#: typeface that disappears fastest is the right one for it.
_BODY_INK = "#000000"
_BODY_FONT = "Arial, 'Helvetica Neue', Helvetica, sans-serif"

#: The only line in the body. Rows are white with a hairline between them: no
#: banding, no vertical rules, nothing that competes with the figures.
_ROW_RULE = "1px solid #E8ECF3"

_TABLE_STYLE = {
    "style_as_list_view": True,
    "style_table": {
        "overflowX": "auto",
        "maxHeight": "440px",
        "overflowY": "auto",
        "border": "1px solid #E1E6EF",
        "borderRadius": "8px",
        # The header is sticky and opaque, so scrolling a long table never
        # leaves the reader looking at figures whose columns they cannot see.
        "backgroundColor": "#FFFFFF",
    },
    "style_cell": {
        "fontFamily": _BODY_FONT,
        "fontSize": "12px",
        "color": _BODY_INK,
        "backgroundColor": "#FFFFFF",
        "padding": "9px 14px",
        "textAlign": "left",
        "border": "none",
        "borderBottom": _ROW_RULE,
        "whiteSpace": "nowrap",
    },
    "style_header": {
        "fontFamily": _BODY_FONT,
        "fontWeight": "700",
        "fontSize": "11px",
        "color": _HEADER_INK,
        "backgroundColor": _HEADER_BG,
        "textTransform": "uppercase",
        "letterSpacing": "0.06em",
        "padding": "10px 14px",
        "border": "none",
        "borderBottom": "none",
        "whiteSpace": "nowrap",
    },
    "style_data": {"backgroundColor": "#FFFFFF"},
    # Native filter inputs inherit the header's navy otherwise, which makes them
    # look like disabled cells.
    "style_filter": {
        "backgroundColor": "#F7F9FC",
        "color": _BODY_INK,
        "fontFamily": _BODY_FONT,
        "border": "none",
        "borderBottom": _ROW_RULE,
    },
}

# Rows per page. Ten keeps the table the same height as the chart it replaces, so
# switching views does not jump the page under the reader.
_PAGE_SIZE = 10

# Rise / fall ink. Matches the chart's semantic colours so a green bar and a
# green arrow mean the same thing on the same screen.
_RISE = "#0F7A33"
_FALL = "#C0393E"

# A cell that reads as a figure: a number, a percentage, a signed change, or
# one of the direction arrows. Used to decide alignment from the DATA rather
# than from a list of column names, which would need editing every time a
# new measure appears.
#: A cell that reads as a figure: a number with an optional currency mark,
#: unit and direction glyph — and possibly TWO of them, since a premium now
#: carries its own movement ("$0.90M  ▼ 25.0%"). Matching the whole
#: cell rather than sniffing for digits keeps "#1 of 2" and a product name on
#: the left where they belong.
_FIGURE = re.compile(r"^\s*(?:[▲▼–]?\s*\$?\s*[\d,.]+\s*(?:%|pts|bn|M|k)?)(?:\s+[▲▼–]?\s*\$?\s*[\d,.]+\s*(?:%|pts|bn|M|k)?)*\s*$|^–$")


def _figure_columns(view: EvidenceView) -> List[str]:
    """Columns whose cells read as figures, so they can be right-aligned.

    Decided by looking at the values: a column is a figure column when every
    non-empty cell in it looks like one. Reading the data rather than the name
    means a new measure aligns correctly the day it is added, and a dimension
    that happens to be numeric-looking (a year, a code) is treated as what its
    cells actually are.
    """
    out: List[str] = []
    for column in view.columns:
        seen = [row.get(column) for row in view.records]
        values = [str(v) for v in seen if v not in (None, "")]
        if values and all(_FIGURE.match(v) for v in values):
            out.append(column)
    return out


def _direction_styles(columns: Sequence[str]) -> List[Dict[str, Any]]:
    """Green for a rise, red for a fall, in every column that carries direction.

    Keyed on the arrow glyph the cell already contains rather than on a column
    name, so a new change column is coloured the moment it exists and a column
    that merely has "change" in its name is not coloured by accident. The glyph
    carries the meaning; this only carries the colour, which is why a screen
    reader and a CSV export lose nothing.
    """
    styles: List[Dict[str, Any]] = []
    for column in columns:
        styles.extend([
            {
                "if": {"column_id": column, "filter_query": f"{{{column}}} contains \"{UP}\""},
                "color": _RISE, "fontWeight": "600",
            },
            {
                "if": {"column_id": column, "filter_query": f"{{{column}}} contains \"{DOWN}\""},
                "color": _FALL, "fontWeight": "600",
            },
        ])
    return styles


def data_table(view: EvidenceView) -> Any:
    """The rows, sortable and filterable in the browser.

    Native sort and filter cost no callback and no re-render, so the reader can
    interrogate the evidence without asking another question.
    """
    numeric = _figure_columns(view)
    return dash_table.DataTable(
        columns=[{"name": c, "id": c} for c in view.columns],
        data=view.records,
        page_size=_PAGE_SIZE,
        sort_action="native",
        filter_action="native" if len(view.records) > _PAGE_SIZE else "none",
        style_data_conditional=[
            # A quiet hover tint: enough to track a row across a wide table,
            # not enough to read as a selection.
            {"if": {"state": "active"}, "backgroundColor": "#F2F6FC",
             "border": "none", "color": _BODY_INK},
            *_direction_styles(view.columns),
        ],
        # Figures right-align so magnitudes line up down the column; the label
        # column stays left. A table of right-ragged numbers is unreadable at a
        # glance, which is the whole job of a table beside a chart.
        style_cell_conditional=[
            {"if": {"column_id": c}, "textAlign": "right"} for c in numeric
        ],
        **_TABLE_STYLE,
    )


def _mode_switch(pane_idx: int) -> Any:
    """The Chart/Data switch for one view (driven by the existing callback)."""
    return html.Div(
        [
            html.Button(
                [html.I(className="bi bi-bar-chart-line"), "Chart"],
                id={"type": "chart-toggle-chart", "idx": pane_idx},
                n_clicks=0,
                className="chart-view-btn active",
            ),
            html.Button(
                [html.I(className="bi bi-table"), "Data"],
                id={"type": "chart-toggle-data", "idx": pane_idx},
                n_clicks=0,
                className="chart-view-btn",
            ),
        ],
        className="chart-view-switch",
    )


def _view_body(view: EvidenceView, pane_idx: int) -> List[Any]:
    """A view's contents: chart + table behind a switch, or just the table."""
    table = html.Div(data_table(view), className="ev-table")
    if not view.has_chart:
        return [
            html.Div(
                [html.I(className="bi bi-table"), html.Span(view.note or "Underlying data")],
                className="ev-note",
            ),
            table,
        ]
    return [
        _mode_switch(pane_idx),
        html.Div(
            dcc.Graph(
                figure=view.figure,
                className="gpt-chart-display",
                config={"displayModeBar": False, "responsive": True},
            ),
            id={"type": "chart-fig", "idx": pane_idx},
        ),
        html.Div(table, id={"type": "chart-table", "idx": pane_idx}, style={"display": "none"}),
    ]


def _tabs(views: Sequence[EvidenceView], idx: int) -> Any:
    """One tab per view. A single view needs no tabs — it is already the answer."""
    if len(views) < 2:
        return None
    return html.Div(
        [
            html.Button(
                [
                    html.I(className="bi bi-bar-chart-line" if v.has_chart else "bi bi-table"),
                    html.Span(v.label),
                ],
                id={"type": "ev-tab", "idx": idx, "view": i},
                n_clicks=0,
                className="ev-tab" + (" active" if i == 0 else ""),
            )
            for i, v in enumerate(views)
        ],
        className="ev-tabs",
    )


def evidence_panel(
    views: Sequence[EvidenceView], idx: int, pane_ids: Sequence[Any] = ()
) -> Any:
    """The whole panel. ``pane_ids`` gives each view its own toggle id.

    ``idx`` scopes the tabs to this panel; ``pane_ids[i]`` scopes view i's
    Chart/Data switch. They are separate because the switch reuses the existing
    per-chart callback, which keys on a flat index.
    """
    if not views:
        return None
    panes = [
        html.Div(
            # A caller that does not supply ids still gets a working panel: the
            # switch only needs an id unique within the page, and the pane's own
            # position gives one.
            _view_body(view, pane_ids[i] if i < len(pane_ids) else f"{idx}-{i}"),
            id={"type": "ev-pane", "idx": idx, "view": i},
            className="ev-pane",
            style={} if i == 0 else {"display": "none"},
        )
        for i, view in enumerate(views)
    ]
    return html.Div(
        [t for t in (_tabs(views, idx),) if t is not None] + panes,
        className="message ev-panel",
    )
