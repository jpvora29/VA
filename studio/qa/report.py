"""QAReport — the pre-export validation contract (Phase 6).

Three severities: ``critical`` blocks export; ``warning`` flags content that is
intentionally blank, manually approved, or a data gap; ``info`` records notes
(e.g. think-cell charts left for manual fill). Pure data — checks live in
``template_checks`` / ``content_checks``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Sequence, Tuple

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"


@dataclass(frozen=True)
class QAIssue:
    code: str
    severity: str                          # CRITICAL | WARNING | INFO
    message: str
    location: str = ""                     # slot key / slide / fact id


@dataclass(frozen=True)
class QAReport:
    issues: Tuple[QAIssue, ...] = field(default_factory=tuple)

    def criticals(self) -> Tuple[QAIssue, ...]:
        return tuple(i for i in self.issues if i.severity == CRITICAL)

    def warnings(self) -> Tuple[QAIssue, ...]:
        return tuple(i for i in self.issues if i.severity == WARNING)

    def notes(self) -> Tuple[QAIssue, ...]:
        return tuple(i for i in self.issues if i.severity == INFO)

    @property
    def blocking(self) -> bool:
        """Export blocks ONLY on critical failures (plan Phase 6)."""
        return bool(self.criticals())

    def counts(self) -> Dict[str, int]:
        return {"critical": len(self.criticals()), "warning": len(self.warnings()),
                "info": len(self.notes()), "total": len(self.issues)}

    def grouped(self) -> Dict[str, Tuple[QAIssue, ...]]:
        """Errors, warnings and notes grouped clearly — the Studio panel shape."""
        return {CRITICAL: self.criticals(), WARNING: self.warnings(), INFO: self.notes()}

    def to_dict(self) -> Dict[str, Any]:
        return {"counts": self.counts(), "blocking": self.blocking,
                "issues": [i.__dict__ for i in self.issues]}


def merge_reports(*reports: QAReport) -> QAReport:
    out = []
    for r in reports:
        out.extend(r.issues)
    return QAReport(issues=tuple(out))


def from_issues(issues: Sequence[QAIssue]) -> QAReport:
    return QAReport(issues=tuple(issues))
