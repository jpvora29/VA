"""Renderers for the bespoke AI-generated widget kinds.

One entry per kind in :data:`_RENDERERS`, so adding a widget is adding a row.

Two families live here:

* the **explainable** widgets (watchlist, headroom, whitespace, quarterly,
  portfolio_map, top_carriers) — every new digest uses these, and they render
  from ``ui.boardroom.widgets_explainable``;
* the **legacy** widgets, some of which wrap the ``_bm_*`` renderers in
  ``ui.components.chatbot`` (imported lazily so this package and the chat module
  can import each other without a cycle). New digests no longer produce the
  score-based ones, but saved boards still contain them — they are drawn from
  :mod:`ui.boardroom.retired`, which shows the figures they carried and never
  their 0-100 score.

Nothing here paints the model's ``tone`` (its opinion of whether a figure is good
news): a colour a reader cannot check is decoration.

Each function takes the widget's ``data`` dict and returns a Dash component body
— the widget chrome (title + edit controls) is added by ``render.py``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from dash import html

from ui.boardroom import retired
from ui.boardroom import widgets_explainable as explainable


def _chatbot():
    # Lazy import breaks the chatbot <-> boardroom import cycle.
    from ui.components import chatbot

    return chatbot


def _untoned(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The items without the model's sentiment colour.

    ``tone`` was the model's opinion of whether a figure was good news, painted
    on as green/amber/red. The figure is on the page; the opinion is not
    something a reader can check, so it is not drawn.
    """
    return [{**item, "tone": "neutral"} for item in items if isinstance(item, dict)]


# ── the overview's written read ──


def _insight_card(card: Dict[str, Any]):
    """One takeaway, led by the figure that proves it when the digest stated one."""
    figure = (card.get("figure") or "").strip()
    detail = (card.get("detail") or "").strip()
    return html.Div(
        [
            html.Div(figure, className="bm-insight-figure") if figure else None,
            html.Div(card.get("headline", ""), className="bm-insight-headline"),
            html.Div(detail, className="bm-insight-detail") if detail else None,
        ],
        className="bm-insight-card bm-insight-plain",
    )


def _render_insights(data: Dict[str, Any]):
    cards = [c for c in (data.get("insights") or []) if isinstance(c, dict)]
    return html.Div([_insight_card(c) for c in cards], className="bm-insight-grid")


def _risk_row(item: Dict[str, Any]):
    """A watch item and the figure behind it. A saved High/Med/Low is not shown."""
    evidence = (item.get("evidence") or "").strip()
    return html.Div(
        [
            html.Span(item.get("label", ""), className="bm-risk-name"),
            html.Span(evidence, className="bm-risk-evidence") if evidence else None,
        ],
        className="bm-risk-item",
    )


def _render_commentary(data: Dict[str, Any]):
    """The key takeaway, then the written sections, then any watch items."""
    cb = _chatbot()
    children = []
    headline = (data.get("headline") or "").strip()
    if headline:
        children.append(
            html.Div(
                [html.Div("Key takeaway", className="bm-takeaway-label"),
                 html.Div(headline, className="bm-headline")],
                className="bm-takeaway",
            )
        )
    sections = [cb._bm_commentary(s) for s in (data.get("sections") or [])]
    if sections:
        children.append(html.Div(sections, className="bm-commentary-cols"))
    risks = [r for r in (data.get("risks") or []) if isinstance(r, dict)]
    if risks:
        children.append(
            html.Div(
                [html.Div("Watch items", className="bm-commentary-heading")]
                + [_risk_row(r) for r in risks],
                className="bm-risk-block",
            )
        )
    return html.Div(children, className="bm-rail bm-brief-rail")


def _render_comparison(data: Dict[str, Any]):
    comparison = dict(data.get("comparison") or {})
    comparison["metrics"] = [
        {**m, "tones": []} for m in (comparison.get("metrics") or []) if isinstance(m, dict)
    ]
    return _chatbot()._bm_comparison(comparison)


def _render_timeline(data: Dict[str, Any]):
    return _chatbot()._bm_timeline(_untoned(data.get("timeline") or []))


# ── the retired score widgets: their evidence, never their score ──


def _evidence_row(row: retired.EvidenceRow):
    fields = [
        html.Div(
            [html.Span(label, className="bm-x-field-label"),
             html.Span(value, className="bm-x-field-value")],
            className="bm-x-field",
        )
        for label, value in row.facts
    ]
    return html.Div(
        [
            html.Div(html.Span(row.title, className="bm-x-row-title"), className="bm-x-row-head"),
            html.Div(fields, className="bm-x-fields") if fields else None,
            html.Div([html.I(className="bi bi-arrow-right-circle"), html.Span(row.note)],
                     className="bm-x-trigger focus") if row.note else None,
        ],
        className="bm-x-row neutral",
    )


def _retired_renderer(kind: str, title: str, icon: str) -> Callable[[Dict[str, Any]], Any]:
    def render(data: Dict[str, Any]):
        rows = retired.evidence_rows(kind, data)
        note = retired.widget_note(kind, data)
        return html.Div(
            [
                html.Div([html.I(className=icon), html.Span(title)], className="bm-section-title"),
                html.Div([_evidence_row(r) for r in rows], className="bm-x-rows") if rows else None,
                html.Div(note, className="bm-x-note") if note else None,
                html.Div([html.I(className="bi bi-info-circle"), html.Span(retired.RETIRED_NOTE)],
                         className="bm-x-empty"),
            ],
            className="bm-widget bm-x",
        )

    return render


_render_opportunity_map = _retired_renderer("opportunity_map", "Market opportunities", "bi bi-globe-americas")
_render_opportunity_radar = _retired_renderer("opportunity_radar", "Opportunity areas", "bi bi-compass")
_render_positioning = _retired_renderer("positioning", "Carriers compared", "bi bi-people")


def _render_battlecards(data: Dict[str, Any]):
    cb = _chatbot()
    return html.Div([cb._bm_battlecard(b) for b in (data.get("battlecards") or [])], className="bm-bc-grid")


_RENDERERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    # explainable (current)
    "watchlist": explainable.render_watchlist,
    "headroom": explainable.render_headroom,
    "whitespace": explainable.render_whitespace,
    "quarterly": explainable.render_quarterly,
    "portfolio_map": explainable.render_portfolio_map,
    "top_carriers": explainable.render_top_carriers,
    "positioning_actual": explainable.render_positioning_actual,
    # legacy (saved boards + the widget library)
    "insights": _render_insights,
    "commentary": _render_commentary,
    "comparison": _render_comparison,
    "timeline": _render_timeline,
    "opportunity_map": _render_opportunity_map,
    "opportunity_radar": _render_opportunity_radar,
    "positioning": _render_positioning,
    "battlecards": _render_battlecards,
}


def render_bespoke(kind: str, data: Dict[str, Any]):
    render = _RENDERERS.get(kind)
    if render is None:
        return html.Div("", className="bm-rail")
    return render(data or {})
