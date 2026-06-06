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
]

LIBRARY_BY_KIND: Dict[str, Dict[str, Any]] = {w["kind"]: w for w in LIBRARY}
CATEGORIES = ["Boardroom widgets", "Add-ons"]


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
