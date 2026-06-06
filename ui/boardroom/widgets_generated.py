"""Renderers for the bespoke AI-generated widget kinds.

These wrap the rich `_bm_*` renderers that already live in
``ui.components.chatbot`` (imported lazily so this package and the chat module can
import each other without a cycle). Each function takes the widget's ``data`` dict
and returns a Dash component body — the widget chrome (title + edit controls) is
added by ``render.py``.
"""
from __future__ import annotations

from typing import Any, Dict

from dash import html


def _chatbot():
    # Lazy import breaks the chatbot <-> boardroom import cycle.
    from ui.components import chatbot

    return chatbot


def render_bespoke(kind: str, data: Dict[str, Any]):
    cb = _chatbot()
    data = data or {}

    if kind == "insights":
        items = data.get("insights") or []
        return html.Div([cb._bm_insight(c) for c in items], className="bm-insight-grid")

    if kind == "commentary":
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

    if kind == "comparison":
        return cb._bm_comparison(data.get("comparison") or {})

    if kind == "timeline":
        return cb._bm_timeline(data.get("timeline") or [])

    if kind == "opportunity_map":
        return cb._bm_opportunity_map(data.get("opportunity_map") or {})

    if kind == "opportunity_radar":
        return cb._bm_radar(data.get("opportunities") or [])

    if kind == "positioning":
        return cb._bm_positioning(data.get("positioning") or {})

    if kind == "battlecards":
        cards = data.get("battlecards") or []
        return html.Div([cb._bm_battlecard(b) for b in cards], className="bm-bc-grid")

    return html.Div("", className="bm-rail")
