"""Widget catalog — metadata for every widget kind.

Two groups:
  * GENERATED — kinds the AI digest produces (bespoke renderers live in
    ``widgets_generated``).
  * LIBRARY  — user-only widgets (the spec's Executive / Planning / Analytical /
    Content library). Most map onto a handful of generic ``content`` types so one
    renderer + one editor serves many kinds; a few have bespoke content.

``content`` drives BOTH the generic renderer and the editor form, so adding a new
library widget is usually just one dict entry here.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ── Generated (AI) widget kinds — bespoke renderers ──
GENERATED: Dict[str, Dict[str, Any]] = {
    "kpi": {"label": "KPI strip", "icon": "bi bi-speedometer2", "content": "kpis"},
    "insights": {"label": "Executive insights", "icon": "bi bi-stars", "content": "bespoke"},
    "commentary": {"label": "Commentary", "icon": "bi bi-card-text", "content": "bespoke"},
    "comparison": {"label": "Comparison", "icon": "bi bi-layout-split", "content": "bespoke"},
    "timeline": {"label": "Insight timeline", "icon": "bi bi-hourglass-split", "content": "bespoke"},
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


# ── User-only widget library ──
LIBRARY: List[Dict[str, Any]] = [
    # Executive
    _lib("executive_takeaway", "Executive takeaway", "bi bi-megaphone", "Executive", "text",
         {"text": "The single most important takeaway for the board."}, "full"),
    _lib("key_message", "Key message", "bi bi-chat-left-text", "Executive", "text",
         {"text": "Key message…"}),
    _lib("decision_required", "Decision required", "bi bi-check2-square", "Executive", "text",
         {"text": "Decision required from the board…"}),
    _lib("decision_rationale", "Decision & rationale", "bi bi-signpost-split", "Executive", "kv",
         {"rows": [["Decision", "…"], ["Rationale", "…"]]}),
    _lib("strategic_priorities", "Strategic priorities", "bi bi-list-stars", "Executive", "list",
         {"items": ["Priority one", "Priority two", "Priority three"]}),
    _lib("recommendation", "Recommendation", "bi bi-hand-index-thumb", "Executive", "text",
         {"text": "We recommend…"}),
    _lib("assumptions_caveats", "Assumptions & caveats", "bi bi-exclamation-circle", "Executive", "list",
         {"items": ["Assumption / caveat…"]}),
    _lib("quote", "Quote / customer voice", "bi bi-quote", "Executive", "quote",
         {"text": "“Customer or stakeholder quote”", "attribution": "— Source"}),
    # Planning
    _lib("action_tracker", "Action tracker", "bi bi-list-check", "Planning", "table",
         {"columns": ["Action", "Owner", "Due", "Status"], "rows": [["…", "…", "…", "Open"]]}, "full"),
    _lib("owner_deadline", "Owner & deadline", "bi bi-person-badge", "Planning", "table",
         {"columns": ["Workstream", "Owner", "Deadline"], "rows": [["…", "…", "…"]]}),
    _lib("milestone_roadmap", "Milestone roadmap", "bi bi-flag", "Planning", "list",
         {"items": ["Q1 — milestone", "Q2 — milestone"]}),
    _lib("dependency_map", "Dependency map", "bi bi-diagram-3", "Planning", "list",
         {"items": ["A depends on B"]}),
    _lib("initiative_portfolio", "Initiative portfolio", "bi bi-kanban", "Planning", "table",
         {"columns": ["Initiative", "Impact", "Effort", "Status"], "rows": [["…", "High", "Med", "Active"]]}, "full"),
    _lib("success_measures", "Success measures", "bi bi-bullseye", "Planning", "list",
         {"items": ["Measure of success…"]}),
    _lib("next_meeting", "Next meeting / review", "bi bi-calendar-event", "Planning", "kv",
         {"rows": [["Next review", "…"], ["Owner", "…"]]}),
    # Analytical
    _lib("kpi_card", "KPI card", "bi bi-speedometer2", "Analytical", "kpis",
         {"kpis": [{"label": "Metric", "value": "0", "delta": "", "tone": "neutral", "icon": "bi bi-graph-up"}]}),
    _lib("target_actual", "Target vs actual", "bi bi-clipboard-check", "Analytical", "table",
         {"columns": ["Metric", "Target", "Actual", "Variance"], "rows": [["…", "…", "…", "…"]]}),
    _lib("variance_bridge", "Variance bridge", "bi bi-bar-chart-steps", "Analytical", "table",
         {"columns": ["Driver", "Impact"], "rows": [["Opening", "…"], ["Driver A", "+…"], ["Closing", "…"]]}),
    _lib("financial_bridge", "Financial bridge", "bi bi-cash-stack", "Analytical", "table",
         {"columns": ["Component", "Value"], "rows": [["Start", "…"], ["Change", "+…"], ["End", "…"]]}),
    _lib("scenario_comparison", "Scenario comparison", "bi bi-columns-gap", "Analytical", "table",
         {"columns": ["Scenario", "Premium", "Outcome"], "rows": [["Base", "…", "…"], ["Upside", "…", "…"]]}, "full"),
    _lib("ranking_table", "Ranking table", "bi bi-list-ol", "Analytical", "table",
         {"columns": ["Rank", "Name", "Value"], "rows": [["1", "…", "…"]]}),
    _lib("risk_register", "Risk register", "bi bi-shield-exclamation", "Analytical", "table",
         {"columns": ["Risk", "Severity", "Mitigation"], "rows": [["…", "High", "…"]]}, "full"),
    _lib("opportunity_pipeline", "Opportunity pipeline", "bi bi-funnel", "Analytical", "table",
         {"columns": ["Opportunity", "Stage", "Value"], "rows": [["…", "Qualify", "…"]]}, "full"),
    _lib("swot", "SWOT", "bi bi-grid-1x2", "Analytical", "quad",
         {"q": [{"title": "Strengths", "items": ["…"]}, {"title": "Weaknesses", "items": ["…"]},
                {"title": "Opportunities", "items": ["…"]}, {"title": "Threats", "items": ["…"]}]}, "lg"),
    _lib("two_by_two", "Two-by-two matrix", "bi bi-grid", "Analytical", "quad",
         {"q": [{"title": "Top-left", "items": []}, {"title": "Top-right", "items": []},
                {"title": "Bottom-left", "items": []}, {"title": "Bottom-right", "items": []}]}, "lg"),
    _lib("heat_map", "Heat map", "bi bi-grid-3x3-gap", "Analytical", "table",
         {"columns": ["", "Col A", "Col B"], "rows": [["Row 1", "70", "30"]]}),
    _lib("funnel", "Funnel", "bi bi-filter", "Analytical", "list",
         {"items": ["Stage 1 — 100", "Stage 2 — 60", "Stage 3 — 25"]}),
    _lib("waterfall", "Waterfall", "bi bi-bar-chart", "Analytical", "table",
         {"columns": ["Step", "Value"], "rows": [["Start", "100"], ["+ Gain", "20"], ["End", "120"]]}),
    _lib("appendix_table", "Appendix table", "bi bi-table", "Analytical", "table",
         {"columns": ["Field", "Value"], "rows": [["…", "…"]]}, "full"),
    # Content
    _lib("rich_text", "Rich text", "bi bi-text-paragraph", "Content", "text",
         {"text": "Type your notes here…"}, "full"),
    _lib("image", "Image", "bi bi-image", "Content", "image",
         {"url": "", "caption": ""}),
    _lib("logo", "Logo", "bi bi-bookmark-star", "Content", "image",
         {"url": "", "caption": ""}, "sm"),
    _lib("divider", "Divider", "bi bi-dash-lg", "Content", "divider", {}, "full"),
    _lib("section_title", "Section title", "bi bi-type-h2", "Content", "section_title",
         {"text": "Section title"}, "full"),
    _lib("footnote", "Footnote", "bi bi-asterisk", "Content", "text",
         {"text": "Footnote…"}, "full"),
    _lib("source_note", "Source note", "bi bi-link-45deg", "Content", "text",
         {"text": "Source: …"}, "full"),
    _lib("attachment_link", "Attachment link", "bi bi-paperclip", "Content", "image",
         {"url": "", "caption": "Attachment"}),
]

LIBRARY_BY_KIND: Dict[str, Dict[str, Any]] = {w["kind"]: w for w in LIBRARY}
CATEGORIES = ["Executive", "Planning", "Analytical", "Content"]


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
