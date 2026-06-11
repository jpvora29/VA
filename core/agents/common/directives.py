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


_CHART_ONLY_PATTERNS = [
    # "just the chart", "only the visual", "chart only", "give me just the graph"
    re.compile(
        rf"\b(?:just|only)\s+(?:the\s+|a\s+|me\s+the\s+)?{_CHART_NOUN}\b"
        rf"|\b{_CHART_NOUN}\s+only\b"
        rf"|\b(?:give|show)\s+me\s+(?:just|only)\s+(?:the\s+|a\s+)?{_CHART_NOUN}\b",
        re.IGNORECASE,
    ),
    # "just show me the visual", "just visualize it"
    re.compile(
        rf"\bjust\s+(?:show|plot|draw|render|display|visuali[sz]e)\b[^.?!]{{0,20}}?"
        rf"\b{_CHART_NOUN}\b",
        re.IGNORECASE,
    ),
]

_TABLE_ONLY_PATTERNS = [
    # "just the table", "table only", "only the numbers", "give me just the numbers"
    re.compile(
        r"\b(?:just|only)\s+(?:the\s+|me\s+the\s+)?(?:tables?|numbers)\b"
        r"|\b(?:tables?|numbers)[\s\-]only\b"
        r"|\bonly\s+(?:tables?|numbers)\b"
        r"|\bin\s+table\s+form\s+only\b",
        re.IGNORECASE,
    ),
]

_DIRECT_PATTERNS = [
    # "in one line", "one sentence", "short/quick answer", "keep it brief", "briefly"
    re.compile(
        r"\bin\s+(?:one|a\s+single)\s+(?:line|sentence)\b"
        r"|\bone[\s\-](?:line|liner|sentence)\b"
        r"|\b(?:short|quick|brief|concise|direct|simple)\s+answer\b"
        r"|\bkeep\s+it\s+(?:short|brief|concise)\b"
        r"|\b(?:just|simply)\s+(?:the\s+)?answer\b"
        r"|\bbriefly\b"
        r"|\btl;?dr\b",
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


def detect_presentation_directive(query: str) -> Optional[str]:
    """Deterministic presentation-mode detection on the raw user query.

    Returns "chart_only" ("just show me the visual"), "table_only" ("just the
    table"), or None when the query states no body-shape preference. chart_only
    is checked first so "just the chart" beats a stray table match; both win
    over the looser `detect_chart_directive` reading at the call site.
    """
    text = query or ""
    if any(p.search(text) for p in _CHART_ONLY_PATTERNS):
        return "chart_only"
    if any(p.search(text) for p in _TABLE_ONLY_PATTERNS):
        return "table_only"
    return None


def detect_depth_directive(query: str) -> Optional[str]:
    """Deterministic depth detection. Returns "direct" ("in one line", "briefly")
    or None when the query states no length preference."""
    text = query or ""
    if any(p.search(text) for p in _DIRECT_PATTERNS):
        return "direct"
    return None


def _directives_of(routing_context: Any) -> Any:
    """Pull `output_directives` off a live model or a checkpoint-deserialized dict."""
    if routing_context is None:
        return None
    return (
        routing_context.get("output_directives")
        if isinstance(routing_context, dict)
        else getattr(routing_context, "output_directives", None)
    )


def _field(directives: Any, name: str, default: str) -> str:
    if directives is None:
        return default
    value = (
        directives.get(name)
        if isinstance(directives, dict)
        else getattr(directives, name, None)
    )
    value = str(value or "").strip().lower()
    return value or default


def presentation_mode(routing_context: Any) -> str:
    """This turn's body shape: 'prose' (default), 'chart_only', or 'table_only'."""
    return _field(_directives_of(routing_context), "presentation", "prose")


def response_depth(routing_context: Any) -> str:
    """This turn's answer length: 'analyst' (default) or 'direct'."""
    return _field(_directives_of(routing_context), "depth", "analyst")


def prose_suppressed(routing_context: Any) -> bool:
    """True when the written answer should be skipped entirely — chart_only and
    table_only both render an artifact with no prose. Lets each insight node
    skip its LLM call instead of generating text the UI would drop."""
    return presentation_mode(routing_context) in ("chart_only", "table_only")


def followups_suppressed(routing_context: Any) -> bool:
    """True when the user asked for a minimal response — no follow-up chips on a
    chart_only / table_only turn or a 'direct' one-line answer."""
    return prose_suppressed(routing_context) or response_depth(routing_context) == "direct"


def charts_suppressed(routing_context: Any) -> bool:
    """True when this turn's directives say to produce NO charts.

    Accepts the live `RoutingContext` model, a checkpoint-deserialized dict, or
    None (older checkpoints / tests) — anything without an explicit "none" /
    table_only means charts stay on, so missing context can never silently
    suppress.
    """
    directives = _directives_of(routing_context)
    if directives is None:
        return False
    if _field(directives, "presentation", "prose") == "table_only":
        return True
    return _field(directives, "charts", "auto") == "none"
