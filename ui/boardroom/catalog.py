"""Widget catalog — metadata for every widget kind.

Two groups:
  * GENERATED — kinds the AI digest produces (bespoke renderers live in
    ``widgets_generated``).
  * LIBRARY  — widgets a user can add by hand. This now contains the *existing*
    fully-editable Boardroom widgets (so you can add another KPI strip, Commentary,
    Insight cards or Timeline) plus a small set of fully-built add-ons. Every entry
    has a working renderer AND a working editor — no placeholders.

``content`` drives BOTH the generic renderer and the editor form.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ── Generated (AI) widget kinds — bespoke renderers ──
GENERATED: Dict[str, Dict[str, Any]] = {
    "kpi": {"label": "KPI strip", "icon": "bi bi-speedometer2", "content": "kpis"},
    "insights": {"label": "Insight cards", "icon": "bi bi-stars", "content": "bespoke"},
    "commentary": {"label": "Commentary", "icon": "bi bi-card-text", "content": "bespoke"},
    "comparison": {"label": "Comparison", "icon": "bi bi-layout-split", "content": "bespoke"},
    # ── explainable widgets (what a new digest produces) ──
    "watchlist": {"label": "Risk & watchlist", "icon": "bi bi-exclamation-diamond", "content": "bespoke"},
    "headroom": {"label": "Product line headroom", "icon": "bi bi-bar-chart-steps", "content": "bespoke"},
    "whitespace": {"label": "Industry whitespace", "icon": "bi bi-grid-1x2", "content": "bespoke"},
    "quarterly": {"label": "Quarterly performance", "icon": "bi bi-calendar3-range", "content": "bespoke"},
    "portfolio_map": {"label": "Product portfolio map", "icon": "bi bi-circle-square", "content": "bespoke"},
    "top_carriers": {"label": "Top carriers", "icon": "bi bi-bar-chart-line", "content": "bespoke"},
    "positioning_actual": {"label": "Positioning (actuals)", "icon": "bi bi-crosshair2", "content": "bespoke"},
    # ── legacy kinds — saved boards still contain these ──
    "timeline": {"label": "Timeline", "icon": "bi bi-hourglass-split", "content": "bespoke"},
    "opportunity_map": {"label": "Opportunity map", "icon": "bi bi-globe-americas", "content": "bespoke"},
    "opportunity_radar": {"label": "Opportunity radar", "icon": "bi bi-radar", "content": "bespoke"},
    "positioning": {"label": "Positioning matrix", "icon": "bi bi-grid-3x3", "content": "bespoke"},
    "battlecards": {"label": "Carrier battlecards", "icon": "bi bi-clipboard-data", "content": "bespoke"},
    "charts": {"label": "Chart", "icon": "bi bi-bar-chart-line", "content": "chart"},
}


def _lib(kind, label, icon, category, content, default_data, size="md"):
    return {
        "kind": kind,
        "label": label,
        "icon": icon,
        "category": category,
        "content": content,
        "default_data": default_data,
        "size": size,
    }


# ── User-addable library ──
#   Boardroom group = the existing, fully-editable widgets (same kinds the AI emits).
#   Add-ons group   = a few brand-new widgets, each fully built (renderer + editor).
LIBRARY: List[Dict[str, Any]] = [
    _lib("kpi", "KPI strip", "bi bi-speedometer2", "Boardroom widgets", "kpis",
         {"kpis": [{"label": "Metric", "value": "0", "delta": "", "tone": "neutral", "icon": "bi bi-graph-up"}]},
         "full"),
    _lib("commentary", "Commentary", "bi bi-card-text", "Boardroom widgets", "bespoke",
         {"headline": "", "sections": [{"heading": "Commentary", "points": ["First point"]}], "risks": []},
         "full"),
    _lib("insights", "Insight cards", "bi bi-stars", "Boardroom widgets", "bespoke",
         {"insights": [{"headline": "New insight", "detail": "Supporting detail", "tone": "neutral", "icon": "bi bi-lightbulb"}]},
         "full"),
    _lib("timeline", "Timeline", "bi bi-hourglass-split", "Boardroom widgets", "bespoke",
         {"timeline": [{"period": "2024", "title": "Milestone", "detail": "", "category": "other", "tone": "neutral"}]},
         "lg"),
    _lib("rich_text", "Rich text", "bi bi-text-paragraph", "Add-ons", "text",
         {"text": "Type your notes here…"}, "full"),
    _lib("action_tracker", "Action tracker", "bi bi-list-check", "Add-ons", "table",
         {"columns": ["Action", "Owner", "Due", "Status"], "rows": [["Define scope", "—", "—", "Open"]]}, "full"),
    _lib("key_message", "Key message", "bi bi-megaphone", "Add-ons", "callout",
         {"text": "The single most important message for the board.", "tone": "neutral"}, "full"),
    _lib("image", "Image / Logo", "bi bi-image", "Add-ons", "image",
         {"url": "", "caption": ""}, "md"),
    # ── Explainable group: business measures only, every classification traceable ──
    _lib("watchlist", "Risk & watchlist", "bi bi-exclamation-diamond", "Explainable", "bespoke",
         {"watchlist": {
             "items": [{"risk": "New watch item", "scope": "", "premium_exposed": "",
                        "premium_exposed_value": None, "movement": "", "movement_pct": None,
                        "adverse": True, "comparison": "", "trigger": "",
                        "consecutive_periods": 1, "breached_kpi": "",
                        "periods_comparable": True, "owner_action": "", "tone": "warn"}],
             "basis": "", "note": "", "thresholds": "", "thresholds_approved": False}},
         "full"),
    _lib("headroom", "Product line headroom", "bi bi-bar-chart-steps", "Explainable", "bespoke",
         {"headroom": {
             "rows": [{"product_line": "Product line", "carrier_premium": "", "carrier_premium_value": None,
                       "marsh_premium": "", "marsh_premium_value": None, "share_of_wallet_pct": None,
                       "share_of_portfolio_pct": None, "whitespace_premium": "",
                       "whitespace_premium_value": None, "market_change": "", "status": "unknown",
                       "focus": ""}],
             "definition": "Whitespace premium = Marsh premium - carrier premium (floored at zero).",
             "basis": "", "note": ""}},
         "full"),
    _lib("whitespace", "Industry whitespace", "bi bi-grid-1x2", "Explainable", "bespoke",
         {"whitespace": {
             "rows": [{"industry": "Industry", "product_line": "", "marsh_premium": "",
                       "marsh_premium_value": None, "carrier_premium": "", "carrier_premium_value": None,
                       "share_of_wallet_pct": None, "share_of_portfolio_pct": None,
                       "peer_share_of_wallet_pct": None, "whitespace_premium": "",
                       "whitespace_premium_value": None, "marsh_change": "", "status": "unknown",
                       "focus_reason": ""}],
             "product_line": "", "product_lines": [],
             "definition": "An industry qualifies when Marsh premium is material and carrier premium is zero or low.",
             "basis": "", "note": ""}},
         "full"),
    _lib("quarterly", "Quarterly performance", "bi bi-calendar3-range", "Explainable", "bespoke",
         {"quarterly": {
             "rows": [{"quarter": "Q1 2026", "premium": "", "premium_value": None,
                       "change_currency": "", "change_pct": None, "share_of_wallet_pct": None,
                       "rank_change": "", "driver": "", "complete": True}],
             "basis": "QoQ", "note": ""}},
         "full"),
    _lib("portfolio_map", "Product portfolio map", "bi bi-circle-square", "Explainable", "bespoke",
         {"portfolio_map": {
             "bubbles": [{"product_line": "Product line", "share_of_wallet_pct": None,
                          "share_of_portfolio_pct": None, "premium": "", "premium_value": None,
                          "marsh_premium": "", "marsh_premium_value": None, "growth": "",
                          "growth_pct": None, "peer_share_of_wallet_pct": None, "tone": "neutral"}],
             "wallet_benchmark_pct": None, "portfolio_benchmark_pct": None,
             "benchmark_label": "Carrier average / market mix", "basis": "", "note": ""}},
         "lg"),
    _lib("top_carriers", "Top carriers", "bi bi-bar-chart-line", "Explainable", "bespoke",
         {"top_carriers": {
             "carriers": [{"carrier": "Carrier", "is_subject": True, "rank": None, "premium": "",
                           "premium_value": None, "share_of_wallet_pct": None, "movement": "",
                           "movement_pct": None}],
             "field_size": None, "scope": "", "basis": "", "note": ""}},
         "full"),
    _lib("positioning_actual", "Positioning (actuals)", "bi bi-crosshair2", "Explainable", "bespoke",
         {"positioning_actual": {
             "points": [{"label": "Carrier", "x_value": None, "x_display": "", "y_value": None,
                         "y_display": "", "is_subject": True, "tone": "neutral"}],
             "x_label": "Share of wallet", "x_unit": "%", "y_label": "Broker score", "y_unit": "",
             "x_benchmark": None, "y_benchmark": None, "benchmark_label": "Peer average", "note": ""}},
         "lg"),
    # ── Analytics group: the score-based widgets the roadmap retired. Kept so a
    #    saved board still opens and a user can still add one deliberately. ──
    _lib("opportunity_radar", "Opportunity radar", "bi bi-radar", "Analytics", "bespoke",
         {"opportunities": [
             {"area": "New opportunity", "dimension": "product", "carrier_level": "",
              "peer_level": "", "gap_score": 50, "recommendation": "", "tone": "good"}]},
         "lg"),
    _lib("opportunity_map", "Heatmap / opportunity map", "bi bi-globe-americas", "Analytics", "bespoke",
         {"opportunity_map": {
             "rows": ["Product A"], "cols": ["Market 1"],
             "cells": [{"row": "Product A", "col": "Market 1", "intensity": 50, "tone": "neutral", "note": ""}],
             "legend": "Darker = higher growth priority"}},
         "full"),
    _lib("positioning", "2x2 peer matrix", "bi bi-grid-3x3", "Analytics", "bespoke",
         {"positioning": {
             "points": [{"label": "Carrier", "premium_strength": 50, "broker_perception": 50,
                         "is_subject": True, "tone": "neutral"}],
             "note": ""}},
         "lg"),
    _lib("comparison", "Comparison table", "bi bi-layout-split", "Analytics", "bespoke",
         {"comparison": {
             "subjects": ["Subject A", "Subject B"],
             "metrics": [{"label": "Metric", "values": ["—", "—"], "tones": []}],
             "highlight": 0}},
         "full"),
    _lib("battlecards", "Carrier battlecards", "bi bi-clipboard-data", "Analytics", "bespoke",
         {"battlecards": [
             {"carrier": "Carrier", "peer_position": "", "strengths": ["Strength"],
              "weaknesses": [], "product_gaps": [], "broker_perception": ""}]},
         "full"),
]

LIBRARY_BY_KIND: Dict[str, Dict[str, Any]] = {w["kind"]: w for w in LIBRARY}
CATEGORIES = ["Boardroom widgets", "Explainable", "Add-ons", "Analytics"]


def library_by_category() -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    for w in LIBRARY:
        out[w["category"]].append(w)
    return out


def content_of(kind: str) -> str:
    if kind in GENERATED:
        return GENERATED[kind]["content"]
    spec = LIBRARY_BY_KIND.get(kind)
    return spec["content"] if spec else "text"


def meta_of(kind: str) -> Dict[str, Any]:
    if kind in GENERATED:
        return GENERATED[kind]
    return LIBRARY_BY_KIND.get(kind, {"label": kind, "icon": "bi bi-square", "content": "text"})


def is_user_addable(kind: str) -> bool:
    return kind in LIBRARY_BY_KIND
