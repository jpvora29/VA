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

from typing import Any, Dict, List, Sequence

from dash import dash_table, dcc, html

from ui.evidence import EvidenceView

_TABLE_STYLE = {
    "style_as_list_view": True,
    "style_table": {"overflowX": "auto", "maxHeight": "440px", "overflowY": "auto"},
    "style_cell": {
        "fontFamily": "'Inter', sans-serif",
        "fontSize": "13px",
        "padding": "8px 12px",
        "textAlign": "left",
        "border": "none",
        "borderBottom": "1px solid rgba(12, 25, 58, 0.06)",
    },
    "style_header": {
        "fontWeight": "600",
        "fontSize": "12px",
        "textTransform": "uppercase",
        "letterSpacing": "0.04em",
        "backgroundColor": "#f5f7fb",
        "borderBottom": "1px solid rgba(12, 25, 58, 0.12)",
    },
}

# Rows per page. Ten keeps the table the same height as the chart it replaces, so
# switching views does not jump the page under the reader.
_PAGE_SIZE = 10


def data_table(view: EvidenceView) -> Any:
    """The rows, sortable and filterable in the browser.

    Native sort and filter cost no callback and no re-render, so the reader can
    interrogate the evidence without asking another question.
    """
    return dash_table.DataTable(
        columns=[{"name": c, "id": c} for c in view.columns],
        data=view.records,
        page_size=_PAGE_SIZE,
        sort_action="native",
        filter_action="native" if len(view.records) > _PAGE_SIZE else "none",
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
