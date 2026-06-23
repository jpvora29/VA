"""QBRContentSpec — the story/evidence layer between facts and slides.

A QBR is not a dump of charts; it is an argument: a thesis, what changed, the
validated drivers, the risks/opportunities, the decisions required, and the
actions (with owners, timing and expected impact) — each backed by evidence and
honest about what the data cannot support.

This module is pure data. `studio/content/evidence.py` builds a `QBRContentSpec`
from computed facts; `studio/content/planner.py` turns it into a `DeckSpec`. The
LLM narrator (later) can author `Finding` prose behind the faithfulness verifier
without changing this shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence

# Canonical insurance-QBR agenda. Sections are emitted only when MATERIAL and the
# data supports them; otherwise they are recorded as data gaps (never filled with
# generic filler).
AGENDA = [
    ("exec_summary", "Executive summary"),
    ("performance", "Performance vs prior period"),
    ("premium_movement", "Premium movement & drivers"),
    ("portfolio_mix", "Portfolio & product mix"),
    ("geo_industry", "Country / industry performance"),
    ("retention", "Retention, renewal & new business"),
    ("rate_volume_mix", "Rate, exposure & volume effects"),
    ("share_position", "Share of wallet & market position"),
    ("survey", "Broker / customer survey signals"),
    ("whitespace", "Whitespace & growth opportunities"),
    ("risks", "Material risks"),
    ("prior_actions", "Actions from the previous QBR"),
    ("decisions", "Decisions & next-quarter priorities"),
    ("appendix", "Appendix & methodology"),
]
AGENDA_LABEL = dict(AGENDA)


@dataclass(frozen=True)
class Evidence:
    """One supporting data point behind a finding."""

    label: str
    value: str
    detail: str = ""
    source: str = "GPR"


@dataclass(frozen=True)
class Finding:
    """A decision-oriented unit of the story — becomes one slide.

    Answers a `question` with an `action_title` (the takeaway), supported by
    `evidence`, with an `implication` and a `recommendation` (owner / due /
    confidence). `materiality` ranks findings for selection.
    """

    section: str                     # agenda section id
    question: str
    action_title: str
    implication: str = ""
    recommendation: str = ""
    owner: Optional[str] = None
    due_date: Optional[str] = None
    confidence: str = "medium"       # high | medium | low
    materiality: float = 0.0         # 0..1, drives slide selection/order
    evidence: Sequence[Evidence] = field(default_factory=tuple)
    takeaways: Sequence[Mapping[str, Any]] = field(default_factory=tuple)  # left-rail points
    visual: Optional[Any] = None     # a single deck Block (chart/table/swot/cards) or None
    visuals: Sequence[Any] = field(default_factory=tuple)  # multiple visuals → dense slide
    kpis: Sequence[Mapping[str, Any]] = field(default_factory=tuple)  # optional KPI band on top
    sources: Sequence[str] = ("GPR",)

    def blocks(self) -> List[Any]:
        """Resolved deck blocks for this finding: optional KPI band, then visuals."""
        from studio.deck.model import KpiBlock

        out: List[Any] = []
        if self.kpis:
            out.append(KpiBlock(self.kpis))
        if self.visuals:
            out.extend(self.visuals)
        elif self.visual is not None:
            out.append(self.visual)
        return out


@dataclass(frozen=True)
class Action:
    """A tracked initiative / next step."""

    title: str
    owner: str = "TBD"
    due_date: str = "Next quarter"
    impact: str = ""
    tag: str = "ACTION"             # ENTER | SCALE | DEFEND | DEEPEN | ACTION
    tone: str = "neutral"
    status: str = "Proposed"       # Proposed | In progress | Done


@dataclass(frozen=True)
class DataGap:
    """A QBR section the current data cannot support — shown, never faked."""

    section: str
    reason: str


@dataclass(frozen=True)
class QBRContentSpec:
    carrier: str
    country: Optional[str]
    period: str
    comparison_period: str
    thesis: str = ""
    what_changed: Sequence[str] = field(default_factory=tuple)
    findings: Sequence[Finding] = field(default_factory=tuple)
    actions: Sequence[Action] = field(default_factory=tuple)
    decisions: Sequence[str] = field(default_factory=tuple)
    data_gaps: Sequence[DataGap] = field(default_factory=tuple)
    sources: Sequence[str] = ("GPR — premium ledger",)

    def finding(self, section: str) -> Optional[Finding]:
        return next((f for f in self.findings if f.section == section), None)
