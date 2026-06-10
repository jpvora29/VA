"""Output-directive detection — the first slice of the per-turn query contract.

Users state presentation preferences inline ("no charts please", "just the
numbers", "show me a chart of ..."). Historically nothing read them: chart
creation was an unconditional pipeline stage, so "don't generate a chart" still
produced one. The contract makes the preference a structured, observable field
(`RoutingContext.output_directives`) that every chart-producing node checks.

Detection is layered, deterministic-first:
  1. `detect_chart_directive` — word-boundary regexes over the ORIGINAL user
     query (before the rephraser can strip the phrase). A hit overrides the LLM.
  2. The context-filler LLM fills `output_directives` for phrasings the
     patterns miss; the deterministic overlay wins whenever both fire.

Suppression ("none") is checked before request ("required") so a negated phrase
like "don't generate a chart" can never be misread as a chart request.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# The chart-ish nouns a directive can target.
_CHART_NOUN = r"(?:charts?|graphs?|plots?|visuals?|visuali[sz]ations?)"

_NONE_PATTERNS = [
    # "no charts", "without a chart", "skip the graph", "omit visuals", ...
    re.compile(
        rf"\b(?:no|without(?:\s+(?:a|any|the))?|skip(?:\s+the)?|omit(?:\s+the)?|"
        rf"hide(?:\s+the)?|exclude(?:\s+the)?)\s+{_CHART_NOUN}\b",
        re.IGNORECASE,
    ),
    # "don't generate a chart", "do not show charts", "never include a graph", ...
    re.compile(
        rf"\b(?:don'?t|do\s+not|never|please\s+don'?t)\s+"
        rf"(?:generate|create|make|include|show|draw|plot|add|build|give(?:\s+me)?|"
        rf"use|render|display)\s+(?:a\s+|any\s+|the\s+)?{_CHART_NOUN}\b",
        re.IGNORECASE,
    ),
    # "text only", "table-only", "numbers only", "only text/tables", "just the numbers"
    re.compile(
        r"\b(?:text|tables?|numbers)[\s\-]only\b"
        r"|\bonly\s+(?:text|tables?|numbers)\b"
        r"|\bjust\s+(?:the\s+)?(?:text|tables?|numbers)\b"
        r"|\bin\s+(?:text|table)\s+form\s+only\b",
        re.IGNORECASE,
    ),
]

_REQUIRED_PATTERNS = [
    # "show/draw/plot ... a chart", "include a graph", "give me a chart of ..."
    re.compile(
        rf"\b(?:show|create|draw|make|generate|include|add|build|plot|give(?:\s+me)?|"
        rf"render|display)\b[^.?!]{{0,40}}?\b{_CHART_NOUN}\b",
        re.IGNORECASE,
    ),
    # "as a chart", "in a graph", "chart it", "visualize ..."
    re.compile(
        rf"\b(?:as|in)\s+a\s+{_CHART_NOUN}\b"
        rf"|\b(?:chart|graph|plot)\s+(?:it|this|that)\b"
        rf"|\bvisuali[sz]e\b",
        re.IGNORECASE,
    ),
]


def detect_chart_directive(query: str) -> Optional[str]:
    """Deterministic chart-directive detection on the raw user query.

    Returns "none" (suppress charts), "required" (user explicitly asked for
    one), or None when no directive phrase is present (leave the LLM's reading
    in place). Suppression is checked FIRST: "don't generate a chart" contains
    "generate a chart", so the negated form must win.
    """
    text = query or ""
    if any(p.search(text) for p in _NONE_PATTERNS):
        return "none"
    if any(p.search(text) for p in _REQUIRED_PATTERNS):
        return "required"
    return None


def charts_suppressed(routing_context: Any) -> bool:
    """True when this turn's directives say to produce NO charts.

    Accepts the live `RoutingContext` model, a checkpoint-deserialized dict, or
    None (older checkpoints / tests) — anything without an explicit "none"
    means charts stay on, so missing context can never silently suppress.
    """
    if routing_context is None:
        return False
    directives = (
        routing_context.get("output_directives")
        if isinstance(routing_context, dict)
        else getattr(routing_context, "output_directives", None)
    )
    if directives is None:
        return False
    charts = (
        directives.get("charts")
        if isinstance(directives, dict)
        else getattr(directives, "charts", None)
    )
    return str(charts or "").strip().lower() == "none"
