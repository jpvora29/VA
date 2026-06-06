"""Renderers for the generic `content` types shared by user-library widgets.

One renderer per content type (text / list / table / kv / quad / image / divider /
section_title / quote / kpis) serves the whole library, so most catalog entries
need no bespoke code. Everything here is self-contained (no dependency on the chat
module) and tone-safe.
"""
from __future__ import annotations

from typing import Any, Dict, List

from dash import dcc, html

_TONES = ("good", "warn", "danger", "neutral")


def tone(value: str | None) -> str:
    v = (value or "neutral").strip().lower()
    return v if v in _TONES else "neutral"


def _kpi_tile(card: Dict[str, Any]):
    t = tone(card.get("tone"))
    delta = card.get("delta") or ""
    return html.Div(
        [
            html.Div(html.I(className=card.get("icon") or "bi bi-graph-up"), className=f"bm-kpi-icon {t}"),
            html.Div(
                [
                    html.Div(card.get("label", ""), className="bm-kpi-label"),
                    html.Div(card.get("value", ""), className="bm-kpi-value"),
                ]
                + ([html.Div(delta, className=f"bm-kpi-delta {t}")] if delta else []),
                className="bm-kpi-copy",
            ),
        ],
        className="bm-kpi-card",
    )


def _table(data: Dict[str, Any]):
    cols = data.get("columns") or []
    rows = data.get("rows") or []
    head = html.Thead(html.Tr([html.Th(str(c)) for c in cols]))
    body = html.Tbody(
        [html.Tr([html.Td(str(c)) for c in (r if isinstance(r, list) else [r])]) for r in rows]
    )
    return html.Table([head, body], className="bm-lib-table")


def _kv(data: Dict[str, Any]):
    rows = data.get("rows") or []
    return html.Div(
        [
            html.Div(
                [
                    html.Div(str(r[0]) if r else "", className="bm-kv-k"),
                    html.Div(str(r[1]) if len(r) > 1 else "", className="bm-kv-v"),
                ],
                className="bm-kv-row",
            )
            for r in rows
        ],
        className="bm-kv",
    )


def _quad(data: Dict[str, Any]):
    quads = (data.get("q") or [])[:4]
    cells = []
    for i, q in enumerate(quads):
        cells.append(
            html.Div(
                [
                    html.Div(q.get("title", ""), className="bm-quad-title"),
                    html.Ul([html.Li(it) for it in (q.get("items") or [])], className="bm-quad-list"),
                ],
                className=f"bm-quad-cell q{i}",
            )
        )
    return html.Div(cells, className="bm-quad")


def _image(data: Dict[str, Any]):
    url = (data.get("url") or "").strip()
    cap = data.get("caption") or ""
    if not url:
        body = html.Div(
            [html.I(className="bi bi-image"), html.Span("Add an image URL in Edit")],
            className="bm-img-placeholder",
        )
    else:
        body = html.Img(src=url, className="bm-img")
    children = [body]
    if cap:
        children.append(html.Div(cap, className="bm-img-caption"))
    return html.Div(children, className="bm-image")


def render_content(content: str, widget: Dict[str, Any]):
    """Render a generic content widget body. Returns a Dash component (or None)."""
    data = widget.get("data") or {}

    if content == "text":
        text = data.get("text") or ""
        paras = [p for p in str(text).split("\n") if p.strip()] or [str(text)]
        return html.Div([html.P(p) for p in paras], className="bm-richtext")

    if content == "list":
        items = data.get("items") or []
        return html.Ul([html.Li(i) for i in items], className="bm-lib-list")

    if content == "table":
        return _table(data)

    if content == "kv":
        return _kv(data)

    if content == "quad":
        return _quad(data)

    if content == "image":
        return _image(data)

    if content == "divider":
        return html.Hr(className="bm-divider")

    if content == "section_title":
        return html.Div(data.get("text", "Section"), className="bm-section-banner")

    if content == "quote":
        return html.Blockquote(
            [
                html.Div(data.get("text", ""), className="bm-quote-text"),
                html.Div(data.get("attribution", ""), className="bm-quote-by"),
            ],
            className="bm-quote",
        )

    if content == "kpis":
        kpis = data.get("kpis") or []
        return html.Div([_kpi_tile(c) for c in kpis], className="bm-kpi-grid")

    # Unknown content — show the raw text fallback so nothing crashes.
    return html.Div(str(data), className="bm-richtext")
