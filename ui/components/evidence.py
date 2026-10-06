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
from typing import Any, Dict, List, Optional, Sequence

from dash import dash_table, dcc, html
from dash.dash_table.Format import Format, Group, Prefix, Scheme, Sign, Symbol

from core.analytics import positioning as P
from ui.evidence import CHART_HEIGHT_PX, EvidenceView

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

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


#: The fallback kind for an untyped column whose cells are all numbers. It sorts
#: and aligns as a figure and is printed exactly as it arrived — deliberately NOT
#: money, because a lens that returns a Year column has an all-numeric column that
#: is not an amount, and "$2,024" is worse than no formatting at all. Only a
#: producer that DECLARES a column money gets a currency mark.
NUMBER = "number"

_FORMATTED = (P.MONEY, P.MONEY_MILLIONS, P.PERCENT, P.SIGNED_PERCENT, P.RANK_KIND, P.COUNT,
              P.SIGNED_COUNT)


def _kind_of(view: EvidenceView, column: str) -> str:
    """What one column IS: what the producer declared, else what its values are.

    A result set that knows its own columns says so (`EvidenceView.column_kinds`).
    Everything else — a lens returning whatever its SQL selected — is read off the
    values, which is only ever a fallback: it can tell a figure from a label, and
    nothing finer than that.
    """
    declared = (view.column_kinds or {}).get(column)
    if declared:
        return declared
    values = [row.get(column) for row in view.records]
    present = [v for v in values if v not in (None, "")]
    if not (present and all(_is_number(v) for v in present)):
        return P.TEXT
    return inferred_kind(column, present)


#: What an untyped column's NAME says it holds. A result set straight from a
#: query ("Premium", "YoY_Growth_%", "Share_of_Wallet") used to print its floats
#: raw — 12345678.912 in a premium column — which reads as a data dump rather
#: than as evidence. The name is a better guide than the values alone.
_YEAR_NAME = re.compile(r"year|quarter|month|period|week|date", re.I)
_RANK_NAME = re.compile(r"\brank", re.I)
_COUNT_NAME = re.compile(r"count|number of|\bn_|clients|carriers|policies|responses", re.I)
_PCT_NAME = re.compile(r"%|pct|percent|share|sow\b|rate|yoy|growth|ratio|penetration", re.I)
_MONEY_NAME = re.compile(r"premium|gwp|amount|revenue|spend|value|headroom|wallet", re.I)

#: Kinds only inferred here (never declared by a producer).
PERCENT_FRACTION = "percent_fraction"
MONEY_BILLIONS = "money_billions"
MONEY_WHOLE = "money_whole"
DECIMAL = "decimal"


def inferred_kind(column: str, values: List[Any]) -> str:
    """A format for a numeric column nobody typed, from its name and values."""
    largest = max(abs(float(v)) for v in values)
    if _YEAR_NAME.search(column):
        return NUMBER
    if _RANK_NAME.search(column):
        return P.RANK_KIND
    if _PCT_NAME.search(column):
        # A share stored as 0.195 prints as 19.5%, one stored as 19.5 as 19.5%.
        return PERCENT_FRACTION if largest <= 1.0 else P.PERCENT
    if _MONEY_NAME.search(column):
        if largest >= 1_000_000_000:
            return MONEY_BILLIONS
        return P.MONEY_MILLIONS if largest >= 1_000_000 else MONEY_WHOLE
    if _COUNT_NAME.search(column) or all(float(v).is_integer() for v in values):
        return P.COUNT
    return DECIMAL


def _format_for(kind: str, unit: str) -> Optional[Format]:
    """How a column of this kind prints. ``None`` for a label column.

    Every format leaves a missing value BLANK (Dash's `nully` default), because
    an absent figure is not a zero — the distinction the whole positioning pack
    is careful about, which a table printing 0 would throw away in the last inch.
    """
    if kind == P.MONEY:
        # One decimal at the table's scale ("$160.0M"); whole units get none.
        return Format(
            scheme=Scheme.fixed, precision=1 if unit else 0, group=Group.yes,
            symbol=Symbol.yes, symbol_prefix="$", symbol_suffix=unit,
        )
    if kind == MONEY_BILLIONS:
        return Format(scheme=Scheme.fixed, precision=1, group=Group.yes,
                      symbol=Symbol.yes, symbol_prefix="$", symbol_suffix="B",
                      ).si_prefix(Prefix.giga)
    if kind == MONEY_WHOLE:
        return Format(scheme=Scheme.fixed, precision=0, group=Group.yes,
                      symbol=Symbol.yes, symbol_prefix="$")
    if kind == PERCENT_FRACTION:
        return Format(scheme=Scheme.percentage, precision=1)
    if kind == DECIMAL:
        return Format(scheme=Scheme.fixed, precision=1, group=Group.yes)
    if kind == P.MONEY_MILLIONS:
        # Raw magnitude, printed in millions: 1_770_000 -> "$1.77M",
        # 2_500_000_000 -> "$2,500.00M". Dash divides by the `si_prefix`, so the
        # rows stay raw and sortable while the cell reads at reporting scale.
        #
        # A FIXED unit, not an automatic one. `Scheme.decimal_si_prefix` switches
        # unit per cell at a threshold the reader cannot see, so one column reads
        # "$840M" then "$2.5G" — incomparable down the page, and "G" is a
        # gigabyte, not a currency unit.
        return Format(
            scheme=Scheme.fixed, precision=1, group=Group.yes,
            symbol=Symbol.yes, symbol_prefix="$", symbol_suffix="M",
        ).si_prefix(Prefix.mega)
    if kind == P.PERCENT:
        return Format(scheme=Scheme.fixed, precision=1,
                      symbol=Symbol.yes, symbol_suffix="%")
    if kind == P.SIGNED_PERCENT:
        # The sign IS the direction, so it is always printed — "+4.2%" and
        # "-25.0%" read as movement where "4.2%" reads as a level.
        return Format(scheme=Scheme.fixed, precision=1, sign=Sign.positive,
                      symbol=Symbol.yes, symbol_suffix="%")
    if kind == P.RANK_KIND:
        return Format(scheme=Scheme.fixed, precision=0,
                      symbol=Symbol.yes, symbol_prefix="#")
    if kind == P.COUNT:
        return Format(scheme=Scheme.fixed, precision=0, group=Group.yes)
    if kind == P.SIGNED_COUNT:
        # "+2" places gained, "-1" lost; a zero prints as "0" (held its place).
        return Format(scheme=Scheme.fixed, precision=0, sign=Sign.positive)
    return None


def _columns_for(view: EvidenceView) -> List[Dict[str, Any]]:
    """Dash column definitions: typed, so the browser sorts them as numbers.

    This is the whole of the sorting fix. The rows arrive as numbers and the
    column declares `type: numeric`; ascending a premium column then gives
    40, 90, 100, 160 rather than the lexical 100, 160, 40, 90 a column of
    pre-formatted strings gave.
    """
    out: List[Dict[str, Any]] = []
    for column in view.columns:
        kind = _kind_of(view, column)
        spec: Dict[str, Any] = {"name": column, "id": column}
        if kind != P.TEXT:
            # Numeric for SORTING; a format only where the producer said what the
            # figure means. An untyped number sorts correctly and prints as it is.
            spec["type"] = "numeric"
        fmt = _format_for(kind, view.unit)
        if fmt is not None:
            spec["format"] = fmt
        out.append(spec)
    return out


def _figure_columns(view: EvidenceView) -> List[str]:
    """Columns that hold figures, so they can be right-aligned."""
    return [c for c in view.columns if _kind_of(view, c) != P.TEXT]


def _direction_styles(view: EvidenceView) -> List[Dict[str, Any]]:
    """Green for a rise, red for a fall, in every column that carries direction.

    Keyed on the VALUE's sign rather than on a glyph in the cell or a word in the
    column name. The sign is the meaning; this only carries the colour, which is
    why a screen reader and a CSV export lose nothing by ignoring it.
    """
    styles: List[Dict[str, Any]] = []
    for column in view.columns:
        kind = _kind_of(view, column)
        signed = kind in (P.SIGNED_PERCENT, P.SIGNED_COUNT) or (
            kind in (P.PERCENT, PERCENT_FRACTION) and re.search(r"yoy|growth|change", column, re.I))
        if not signed:
            continue
        styles.extend([
            {"if": {"column_id": column, "filter_query": f"{{{column}}} > 0"},
             "color": _RISE, "fontWeight": "600"},
            {"if": {"column_id": column, "filter_query": f"{{{column}}} < 0"},
             "color": _FALL, "fontWeight": "600"},
        ])
    return styles


def data_table(view: EvidenceView) -> Any:
    """The rows, sortable and filterable in the browser.

    Native sort and filter cost no callback and no re-render, so the reader can
    interrogate the evidence without asking another question — provided the
    columns are typed, which is what `_columns_for` is for.
    """
    numeric = _figure_columns(view)
    return dash_table.DataTable(
        columns=_columns_for(view),
        data=view.records,
        page_size=_PAGE_SIZE,
        sort_action="native",
        # A filter row whenever there is something to find: type "Singap" under
        # Country or "Prop" under Product line. Case-insensitive.
        filter_action="native" if len(view.records) > 3 else "none",
        filter_options={"case": "insensitive", "placeholder_text": "Filter…"},
        style_data_conditional=[
            # A quiet hover tint: enough to track a row across a wide table,
            # not enough to read as a selection.
            {"if": {"state": "active"}, "backgroundColor": "#F2F6FC",
             "border": "none", "color": _BODY_INK},
            *_direction_styles(view),
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
                [html.I(className="bi bi-table"), "Table"],
                id={"type": "chart-toggle-data", "idx": pane_idx},
                n_clicks=0,
                className="chart-view-btn",
            ),
        ],
        className="chart-view-switch",
    )


def _lazy_chart(view: EvidenceView) -> Any:
    """A chart that is drawn the first time its tab is opened.

    A panel's hidden tabs used to mount a full Plotly graph each — three or four
    per answer — so opening a long conversation drew dozens of charts nobody was
    looking at. This placeholder carries the figure as JSON and
    `assets/chat_experience.js` plots it on first view.
    """
    import plotly.io as pio

    return html.Div(
        className="ev-lazy-chart",
        style={"minHeight": f"{CHART_HEIGHT_PX}px"},
        **{"data-figure": pio.to_json(view.figure, validate=False)},
    )


def _graph(view: EvidenceView, *, lazy: bool) -> Any:
    return _lazy_chart(view) if lazy else dcc.Graph(
        figure=view.figure,
        className="gpt-chart-display",
        config={"displayModeBar": False, "responsive": True},
    )


def _view_head(title: str, subtitle: str = "", switch: Any = None) -> Optional[Any]:
    """What a view shows, in words, with the Chart/Table switch on the right."""
    if not (title or subtitle or switch is not None):
        return None
    return html.Div(
        [
            html.Div(
                [
                    html.Div(title, className="ev-view-title") if title else None,
                    html.Div(subtitle, className="ev-view-sub") if subtitle else None,
                ],
                className="ev-view-text",
            ),
            switch,
        ],
        className="ev-view-head",
    )


def _view_body(view: EvidenceView, pane_idx: Any, *, lazy: bool = False) -> List[Any]:
    """A view's contents: chart + its own rows behind a switch, or just the rows."""
    table = html.Div(data_table(view), className="ev-table")
    if not view.has_chart:
        return [_view_head(view.title or view.label, view.note), table]
    return [
        _view_head(view.title, "", _mode_switch(pane_idx)),
        html.Div(_graph(view, lazy=lazy), id={"type": "chart-fig", "idx": pane_idx}),
        html.Div(table, id={"type": "chart-table", "idx": pane_idx}, style={"display": "none"}),
    ]


def _tabs(views: Sequence[EvidenceView], idx: Any) -> Any:
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


def _panel_head(label: str, switch: Any = None) -> Optional[Any]:
    """The panel's own heading ("Supporting evidence"), with the switch when it
    governs the whole panel."""
    if not (label or switch is not None):
        return None
    return html.Div(
        [html.Div(label, className="ev-panel-label") if label else html.Span(), switch],
        className="ev-panel-head",
    )


def _chart_pane(view: EvidenceView, idx: Any, i: int, *, lazy: bool) -> Any:
    return html.Div(
        [_view_head(view.title or view.label), _graph(view, lazy=lazy)],
        id={"type": "ev-pane", "idx": idx, "view": i},
        className="ev-pane",
        style={} if i == 0 else {"display": "none"},
    )


def _table_block(view: EvidenceView, *, named: bool) -> Any:
    """One table with what it is above it (its market's name when there are several)."""
    heading = view.label if named and view.label not in ("", "Position") else ""
    return html.Div(
        [
            _view_head(heading or view.title or "Position table", view.note),
            html.Div(data_table(view), className="ev-table"),
        ],
        className="ev-table-block",
    )


def paired_panel(charts: Sequence[EvidenceView], tables: Sequence[EvidenceView],
                 idx: Any, switch_idx: Any, *, label: str = "") -> Any:
    """Charts and the position table as the two sides of ONE panel.

    The reader picks a chart along the strip, and the Chart/Table switch in the
    panel's header turns the whole panel to the position table — the same table
    whichever chart was showing, because it is the table every chart (and every
    sentence above them) was drawn from. Several markets stack their tables,
    each under its market's name.

    The switch reuses the per-chart toggle callback on ONE index: `chart-fig`
    wraps the charts, `chart-table` the tables.
    """
    named = len(tables) > 1
    return html.Div(
        [
            _panel_head(label, _mode_switch(switch_idx)),
            html.Div(
                [t for t in (_tabs(charts, idx),) if t is not None] + [
                    _chart_pane(view, idx, i, lazy=i != 0)
                    for i, view in enumerate(charts)
                ],
                id={"type": "chart-fig", "idx": switch_idx},
            ),
            html.Div(
                [_table_block(view, named=named) for view in tables],
                id={"type": "chart-table", "idx": switch_idx},
                className="ev-tables",
                style={"display": "none"},
            ),
        ],
        className="message ev-panel is-paired",
    )


def evidence_panel(
    views: Sequence[EvidenceView], idx: Any, pane_ids: Sequence[Any] = (), *, label: str = "",
) -> Any:
    """The whole panel. ``pane_ids`` gives each view its own toggle id.

    ``idx`` scopes the tabs to this panel; ``pane_ids[i]`` scopes view i's
    Chart/Table switch. They are separate because the switch reuses the existing
    per-chart callback, which keys on a flat index.

    When the answer has charts AND a position table, the table is the Table side
    of every chart (:func:`paired_panel`) rather than a tab of its own, so it is
    one click from whatever the reader is looking at. Otherwise each view keeps
    its own chart/rows switch.
    """
    if not views:
        return None
    charts = [v for v in views if v.has_chart]
    tables = [v for v in views if not v.has_chart]
    if charts and any(v.is_position_table for v in tables):
        # Every table rides on the Table side, position tables first.
        ordered = sorted(tables, key=lambda v: not v.is_position_table)
        switch_idx = pane_ids[0] if pane_ids else f"{idx}-0"
        return paired_panel(charts, ordered, idx, switch_idx, label=label)
    # One chart per panel is drawn eagerly — the first one — which also makes
    # sure Plotly is loaded on the page; every other chart waits for its tab.
    eager = next((i for i, v in enumerate(views) if v.has_chart), None)
    panes = [
        html.Div(
            # A caller that does not supply ids still gets a working panel: the
            # switch only needs an id unique within the page, and the pane's own
            # position gives one.
            _view_body(view, pane_ids[i] if i < len(pane_ids) else f"{idx}-{i}",
                       lazy=view.has_chart and i != eager),
            id={"type": "ev-pane", "idx": idx, "view": i},
            className="ev-pane",
            style={} if i == 0 else {"display": "none"},
        )
        for i, view in enumerate(views)
    ]
    return html.Div(
        [h for h in (_panel_head(label), _tabs(views, idx)) if h is not None] + panes,
        className="message ev-panel",
    )
