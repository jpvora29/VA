"""Human-readable QA explanation — a deep agent explains, never re-grades.

The plan allows deep agents to *explain* QA issues, not decide them: the
deterministic `QAReport` stays the authority, and this module only turns it
into a short author-facing briefing. Deterministic fallback is a plain counts
summary, so the Studio review panel always has something to show. The agent
run loads the ``qa-explainer`` skill for tone and structure; its prose is
discarded if it names a banned peer carrier.
"""
from __future__ import annotations

import json
from typing import Sequence

from studio.qa.report import QAReport


def summarize_qa_counts(report: QAReport) -> str:
    """The always-available one-line summary, purely from the report."""
    counts = report.counts()
    if not counts["total"]:
        return "No QA issues — the deck exported clean."
    verdict = "Export blocked" if report.blocking else "Export proceeded"
    parts = [f"{counts[sev]} {sev}" for sev in ("critical", "warning", "info") if counts[sev]]
    return f"{verdict}: {', '.join(parts)} issue(s)."


def _report_payload(report: QAReport, subject: str) -> str:
    return json.dumps({"subject": subject, "qa_report": report.to_dict()}, ensure_ascii=False)


_SYSTEM = """You brief the author of a QBR deck on its QA report, using the
qa-explainer skill. Explain only the issues in the report — the severities and
the export decision are already final and must be restated, never re-judged."""


def explain_qa_report(
    report: QAReport, *, subject: str = "", forbidden_names: Sequence[str] = ()
) -> str:
    """Plain-language QA briefing: deep agent when available, counts otherwise."""
    base = summarize_qa_counts(report)
    if not report.issues:
        return base
    from studio.ai.deep_agent import deep_agent_available, run_deep_agent

    if not deep_agent_available():
        return base
    text = run_deep_agent(
        _report_payload(report, subject), system_prompt=_SYSTEM,
        tier="fast", node="qa-explainer",
    )
    if not text:
        return base
    low = text.lower()
    if any(name and name.lower() in low for name in forbidden_names):
        return base
    return text
