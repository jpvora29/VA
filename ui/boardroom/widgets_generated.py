"""Renderers for the bespoke AI-generated widget kinds.

One entry per kind in :data:`_RENDERERS`, so adding a widget is adding a row.

Two families live here:

* the **explainable** widgets (watchlist, headroom, whitespace, quarterly,
  portfolio_map, top_carriers) — every new digest uses these, and they render
  from ``ui.boardroom.widgets_explainable``;
* the **legacy** widgets, which wrap the rich ``_bm_*`` renderers in
  ``ui.components.chatbot`` (imported lazily so this package and the chat module
  can import each other without a cycle). New digests no longer produce the
  score-based ones, but saved boards still contain them.

Each function takes the widget's ``data`` dict and returns a Dash component body
— the widget chrome (title + edit controls) is added by ``render.py``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from dash import html

from ui.boardroom import widgets_explainable as explainable


def _chatbot():
    # Lazy import breaks the chatbot <-> boardroom import cycle.
    from ui.components import chatbot

    return chatbot


# ── legacy renderers (saved boards) ──


def _render_insights(data: Dict[str, Any]):
    cb = _chatbot()
    return html.Div([cb._bm_insight(c) for c in (data.get("insights") or [])], className="bm-insight-grid")


def _render_commentary(data: Dict[str, Any]):
    cb = _chatbot()
    children = []
    headline = (data.get("headline") or "").strip()
    if headline:
        children.append(html.Div(headline, className="bm-headline"))
    children.extend(cb._bm_commentary(s) for s in (data.get("sections") or []))
    risks = data.get("risks") or []
    if risks:
        children.append(
            html.Div(
                [html.Div("Risks & watch items", className="bm-commentary-heading")]
                + [cb._bm_risk(r) for r in risks],
                className="bm-risk-block",
            )
        )
    return html.Div(children, className="bm-rail")


def _render_comparison(data: Dict[str, Any]):
    return _chatbot()._bm_comparison(data.get("comparison") or {})


def _render_timeline(data: Dict[str, Any]):
    return _chatbot()._bm_timeline(data.get("timeline") or [])


def _render_opportunity_map(data: Dict[str, Any]):
    return _chatbot()._bm_opportunity_map(data.get("opportunity_map") or {})


def _render_opportunity_radar(data: Dict[str, Any]):
    return _chatbot()._bm_radar(data.get("opportunities") or [])


def _render_positioning(data: Dict[str, Any]):
    return _chatbot()._bm_positioning(data.get("positioning") or {})


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
