"""QA / critic agent — a guardrail pass over the assembled deck.

Reviews the finished `DeckSpec` for weak action titles, likely overflow, unsupported
causal language, contradictions and duplicated insights, and returns a structured
issue list. Issues are stashed on `deck.meta['critic_issues']` for the Review view to
surface; they never block generation. Deterministic fallback: a small rule-based
check (empty titles / missing evidence) so Review is useful even with no LLM.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Dict, List

from logger import get_logger
from studio.ai.client import llm_available, structured
from studio.ai.models import CriticReport
from studio.deck.model import DeckSpec

logger = get_logger(__name__)

_CONTENT_LAYOUTS = {"insight", "decision", "exec"}

_SYSTEM = """You review an insurance QBR deck for quality. Flag: weak/topic-only action
titles (not a takeaway sentence), unsupported causal claims ('X caused Y' without a
driver), contradictions between slides, duplicated insights, and titles that don't
match their evidence. Return concise issues with the slide idx and a severity
(info|warn|error). Do not invent numbers."""


def _rule_based(deck: DeckSpec) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for i, s in enumerate(deck.slides):
        if s.layout not in _CONTENT_LAYOUTS:
            continue
        if not s.title.strip():
            issues.append({"idx": i, "severity": "error", "category": "title", "message": "Slide has no action title."})
        elif len(s.title.split()) <= 3:
            issues.append({"idx": i, "severity": "warn", "category": "title", "message": "Action title is very short — make it a full takeaway."})
        if s.layout == "insight" and not s.evidence and not s.takeaways:
            issues.append({"idx": i, "severity": "warn", "category": "evidence", "message": "No evidence or takeaways linked to this slide."})
    return issues


def review_deck(deck: DeckSpec) -> DeckSpec:
    """Attach a critic report to ``deck.meta['critic_issues']`` (AI, else rule-based)."""
    issues: List[Dict[str, Any]] = []
    if llm_available():
        payload = json.dumps(
            [{"idx": i, "layout": s.layout, "title": s.title,
              "takeaways": [t.get("text", "") for t in s.takeaways]}
             for i, s in enumerate(deck.slides) if s.layout in _CONTENT_LAYOUTS],
            ensure_ascii=False,
        )
        report = structured(CriticReport, _SYSTEM, payload, node="critic")
        if report is not None:
            issues = [iss.model_dump() for iss in report.issues]
    if not issues:
        issues = _rule_based(deck)
    logger.info("studio.ai critic raised %d issue(s)", len(issues))
    return replace(deck, meta={**(deck.meta or {}), "critic_issues": issues})
