"""Pre-export QA (Phase 6): template checks + content checks → one QAReport.

Export blocks only on critical failures; warnings cover intentionally blank or
manually approved content; notes record what was done.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from studio.qa.content_checks import (
    check_commentary_citations,
    check_commentary_verification,
    check_confidentiality,
    check_evidence_gaps,
)
from studio.qa.report import CRITICAL, INFO, WARNING, QAIssue, QAReport, merge_reports
from studio.qa.template_checks import (
    check_binding_health,
    check_charts,
    check_intentional_blanks,
    check_required_slots,
)

__all__ = [
    "QAIssue", "QAReport", "CRITICAL", "WARNING", "INFO",
    "merge_reports", "run_qbr_qa",
    "check_required_slots", "check_charts", "check_intentional_blanks",
    "check_binding_health", "check_commentary_citations",
    "check_commentary_verification", "check_confidentiality", "check_evidence_gaps",
]


def run_qbr_qa(
    *,
    fields: Mapping[str, Mapping[str, Any]],
    values: Mapping[str, Any],
    commentary: Sequence = (),
    pack=None,
    binding_map=None,
    descriptor=None,
    hidden_slides=None,
    banned_names: Sequence[str] = (),
) -> QAReport:
    """Run every applicable check; return one grouped report (pure)."""
    issues = []
    issues += check_required_slots(fields, hidden_slides=list(hidden_slides or []))
    issues += check_charts(fields, values)
    if binding_map is not None:
        issues += check_intentional_blanks(binding_map)
        issues += check_binding_health(binding_map, descriptor)
    if pack is not None:
        issues += check_commentary_citations(commentary, pack)
        issues += check_evidence_gaps(pack)
    issues += check_commentary_verification(commentary)
    if banned_names:
        issues += check_confidentiality(commentary, banned_names)
    return QAReport(issues=tuple(issues))
