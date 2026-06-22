"""Deterministic Studio renderers — facts/rows → gorgeous Dash components.

Pure presentation: every number shown here is placed by the renderer (never typed
by the LLM), satisfying the faithfulness contract (DESIGN.md §2). Components reuse
the app's design tokens (Inter, Marsh navy/electric-blue, soft shadows) via the
``studio-*`` classes in ``assets/studio.css`` and the brand chart palette.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import plotly.graph_objects as go
from dash import dcc, html

from studio.page.format import money, pct, rank_label
from ui.color_pallet import ColorPalette

_NAVY = "#000F47"
_INK = "#1c2636"
_MUTED = "#5b6577"


# ── headers & shells ────────────────────────────────────────────────────────


def page_header(
    eyebrow: str, title: str, subtitle: str = "", *, export: bool = True
) -> html.Div:
    right = (
        html.Button(
            [html.I(className="bi bi-file-earmark-arrow-down"), "Export"],
            className="studio-export-btn",
        )
        if export
        else None
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(eyebrow, className="studio-eyebrow"),
                    html.H1(title, className="studio-page-title"),
                    html.P(subtitle, className="studio-page-subtitle") if subtitle else None,
                ],
                className="studio-page-head-copy",
            ),
            right,
        ],
        className="studio-page-head",
    )


def kpi_strip(kpis: Sequence[Mapping[str, Any]]) -> html.Div:
    """KPI cards: each ``{label, value, delta?, tone?, icon?}``."""
    cards = []
    for k in kpis:
        tone = k.get("tone", "neutral")
        delta = k.get("delta")
        cards.append(
            html.Div(
                [
                    html.Div(
                        html.I(className=f"bi {k.get('icon', 'bi-graph-up')}"),
                        className=f"studio-kpi-icon {tone}",
                    ),
                    html.Div(
                        [
                            html.Div(k["label"], className="studio-kpi-label"),
                            html.Div(k["value"], className="studio-kpi-value"),
                            html.Div(delta, className=f"studio-kpi-delta {tone}")
                            if delta
                            else None,
                        ],
                        className="studio-kpi-copy",
                    ),
                ],
                className="studio-kpi-card",
            )
        )
    return html.Div(cards, className="studio-kpi-grid")


def section(
    title: str,
    children: Any,
    *,
    eyebrow: str = "",
    accent: str = "blue",
    aside: Optional[Any] = None,
) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(className=f"studio-accent {accent}"),
                            html.Div(
                                [
                                    html.Div(eyebrow, className="studio-section-eyebrow")
                                    if eyebrow
                                    else None,
                                    html.H3(title, className="studio-section-title"),
                                ]
                            ),
                        ],
                        className="studio-section-heading",
                    ),
                    aside,
                ],
                className="studio-section-head",
            ),
            html.Div(children, className="studio-section-body"),
        ],
        className="studio-panel",
    )


def commentary(
    headline: str,
    points: Sequence[Mapping[str, Any]],
    *,
    title: str = "Executive Commentary",
    actions: Optional[Sequence[str]] = None,
) -> html.Div:
    """QBR-style narrative block. ``points`` = ``[{label?, text, tone?}]``.

    In production the LLM narrator writes ``headline``/``points`` from the fact
    store and the faithfulness verifier checks every number/entity before render.
    """
    items = [
        html.Div(
            [
                html.Span(className=f"studio-cmt-dot {p.get('tone', 'neutral')}"),
                html.Div(
                    [
                        html.Span(p["label"] + "  ", className="studio-cmt-label")
                        if p.get("label")
                        else None,
                        html.Span(p["text"], className="studio-cmt-text"),
                    ],
                    className="studio-cmt-copy",
                ),
            ],
            className="studio-cmt-item",
        )
        for p in points
    ]
    action_block = (
        html.Div(
            [
                html.Div(
                    [html.I(className="bi bi-flag-fill"), "Recommended actions"],
                    className="studio-cmt-actions-head",
                ),
                html.Ul([html.Li(a) for a in actions], className="studio-cmt-actions"),
            ],
            className="studio-cmt-actions-wrap",
        )
        if actions
        else None
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [html.I(className="bi bi-quote"), title],
                        className="studio-cmt-title",
                    ),
                    html.Span("AI-narrated · fact-verified", className="studio-cmt-badge"),
                ],
                className="studio-cmt-head",
            ),
            html.P(headline, className="studio-cmt-headline"),
            html.Div(items, className="studio-cmt-list"),
            action_block,
        ],
        className="studio-commentary",
    )


# ── tables ──────────────────────────────────────────────────────────────────


def _cell(value: Any, kind: str) -> Any:
    if kind == "money":
        return money(value)
    if kind == "pct":
        return pct(value)
    if kind == "pct_signed":
        return pct(value, signed=True)
    if kind == "rank":
        return html.Span(rank_label(value), className="studio-rank-badge")
    if kind == "delta":
        cls = "good" if (value or 0) > 0 else "danger" if (value or 0) < 0 else "neutral"
        arrow = "▲" if (value or 0) > 0 else "▼" if (value or 0) < 0 else "—"
        return html.Span([arrow, " ", pct(value, signed=True)], className=f"studio-delta {cls}")
    return "—" if value in (None, "") else str(value)


def fact_table(
    rows: List[Mapping[str, Any]],
    columns: Sequence[Mapping[str, str]],
    *,
    hidden: int = 0,
) -> html.Div:
    """Render rows as a refined table. ``columns`` = ``[{key,label,kind,align}]``.

    ``hidden`` > 0 inserts a labeled gap row (the truncation rule's collapsed
    middle), so the reader always knows rows were elided.
    """
    head = html.Thead(
        html.Tr(
            [
                html.Th(
                    c["label"],
                    className=f"studio-th {c.get('align', 'left')}",
                )
                for c in columns
            ]
        )
    )
    body_rows: List[Any] = []
    split = len(rows)
    for i, row in enumerate(rows):
        # If truncated, draw the gap between the top block and the bottom block.
        if hidden and i == split - _bottom_count(rows, hidden):
            body_rows.append(_gap_row(len(columns), hidden))
        body_rows.append(
            html.Tr(
                [
                    html.Td(
                        _cell(row.get(c["key"]), c.get("kind", "text")),
                        className=f"studio-td {c.get('align', 'left')}",
                    )
                    for c in columns
                ]
            )
        )
    return html.Div(
        html.Table([head, html.Tbody(body_rows)], className="studio-table"),
        className="studio-table-wrap",
    )


def _bottom_count(rows: List[Mapping[str, Any]], hidden: int) -> int:
    # The truncation rule keeps top_n + bottom_n; the gap sits before the bottom
    # block. Default split is half when both blocks are equal; callers using the
    # rule pass pre-split rows so this is purely cosmetic placement.
    return len(rows) // 2 if hidden else 0


def _gap_row(span: int, hidden: int) -> html.Tr:
    return html.Tr(
        html.Td(
            html.Span(
                [html.I(className="bi bi-three-dots"), f"  {hidden} rows hidden  "],
                className="studio-gap-pill",
            ),
            colSpan=span,
            className="studio-gap-cell",
        ),
        className="studio-gap-row",
    )


# ── charts ──────────────────────────────────────────────────────────────────


def _base_layout(height: int = 280) -> Dict[str, Any]:
    return dict(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, sans-serif", color=_INK, size=12),
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(12,25,58,0.06)", zeroline=False),
    )


def bar_chart(
    labels: Sequence[str], values: Sequence[float], *, horizontal: bool = True, height: int = 280
) -> dcc.Graph:
    colors = ColorPalette.sequential(len(values)) or [ColorPalette.blue[0]]
    if horizontal:
        labels = list(reversed(labels))
        values = list(reversed(values))
        colors = list(reversed(colors))
        fig = go.Figure(
            go.Bar(
                x=values,
                y=labels,
                orientation="h",
                marker=dict(color=colors, line=dict(width=0)),
                text=[money(v) for v in values],
                textposition="auto",
                textfont=dict(color="#ffffff", size=11),
                hovertemplate="%{y}: %{x:,.0f}<extra></extra>",
            )
        )
        layout = _base_layout(height)
        layout["yaxis"] = dict(showgrid=False, zeroline=False, automargin=True)
        layout["xaxis"] = dict(showgrid=True, gridcolor="rgba(12,25,58,0.06)", zeroline=False)
    else:
        fig = go.Figure(
            go.Bar(x=labels, y=values, marker=dict(color=colors, line=dict(width=0)))
        )
        layout = _base_layout(height)
    fig.update_layout(**layout, bargap=0.35)
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, className="studio-fig")


def waterfall(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    height: int = 280,
    total_label: str = "Total gap",
) -> dcc.Graph:
    """Waterfall of per-category contributions summing to a total.

    Used for the rank "gap to next rank" story: each bar is how much the next-rank
    carrier out-earns you in one product line; the bars accumulate to the total
    premium gap to close. Positive values rise (a gap to close)."""
    labels = list(labels)
    values = [float(v) for v in values]
    measures = ["relative"] * len(labels) + ["total"]
    x = labels + [total_label]
    y = values + [sum(values)]
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=measures,
            x=x,
            y=y,
            text=[money(v) for v in y],
            textposition="outside",
            textfont=dict(size=10),
            connector=dict(line=dict(color="rgba(12,25,58,0.25)")),
            increasing=dict(marker=dict(color=ColorPalette.blue[0] if ColorPalette.blue else "#0b4bff")),
            decreasing=dict(marker=dict(color="#57C67A")),
            totals=dict(marker=dict(color=_NAVY)),
        )
    )
    layout = _base_layout(height)
    layout["xaxis"] = dict(showgrid=False, zeroline=False, automargin=True)
    fig.update_layout(**layout)
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, className="studio-fig")


def donut(labels: Sequence[str], values: Sequence[float], *, height: int = 260) -> dcc.Graph:
    fig = go.Figure(
        go.Pie(
            labels=list(labels),
            values=list(values),
            hole=0.62,
            marker=dict(colors=ColorPalette.sequential(len(values)), line=dict(color="#fff", width=2)),
            textinfo="label+percent",
            textfont=dict(family="Arial, sans-serif", size=11),
            sort=False,
        )
    )
    fig.update_layout(**_base_layout(height))
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, className="studio-fig")
