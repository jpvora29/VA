"""Deterministic classification of a slice — strengths, weaknesses and the pattern behind
them (design Sections 5, 9, 11).

A label always names its basis ("growth 8.0 percentage points below the Marsh book"),
never just "weak". A portfolio leader is the largest product by carrier premium; calling
it a relative strength additionally needs a benchmark. A single weak metric triggers
review, not a blanket weak label.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from studio.exec_summary.config import Materiality
from studio.exec_summary.metrics import SliceMetrics
from studio.exec_summary.survey import ScoreLine

LEADER = "portfolio_leader"
STRENGTH = "relative_strength"
ATTENTION = "needs_attention"

SEVERITY_STRENGTH = "strength"
SEVERITY_ATTENTION = "attention"
SEVERITY_NEUTRAL = "neutral"

# Interpretation matrix (design Section 9) — the rule id travels with every finding.
RULE_REL_UNDERPERF = "PAT_RELATIVE_UNDERPERFORMANCE"   # carrier falls, Marsh and peers grow
RULE_SHARED_PRESSURE = "PAT_SHARED_BOOK_PRESSURE"      # everyone declines
RULE_GROW_BELOW_MARSH = "PAT_GROWS_BELOW_MARSH"        # grows, but loses share
RULE_OUTPERFORM = "PAT_OUTPERFORMS_BOOK"               # grows faster than the Marsh book
RULE_IN_LINE = "PAT_IN_LINE"
RULE_UNAVAILABLE = "PAT_COMPARISON_UNAVAILABLE"
RULE_SURVEY_WEAK_TOO = "PAT_COMMERCIAL_AND_SURVEY_WEAK"
RULE_SURVEY_STRONG = "PAT_COMMERCIAL_WEAK_SURVEY_STRONG"


@dataclass(frozen=True)
class Classification:
    labels: Tuple[str, ...]
    pattern: str
    severity: str
    reasons: Tuple[str, ...]
    survey_rule: Optional[str] = None

    @property
    def rule_ids(self) -> Tuple[str, ...]:
        return tuple(r for r in (self.pattern, self.survey_rule) if r)


def pattern_of(m: SliceMetrics) -> str:
    """Which row of the interpretation matrix the commercial movement falls in."""
    c, mk, p = m.carrier_growth, m.marsh_growth, m.peer.growth
    if not (c.valid and mk.valid):
        return RULE_UNAVAILABLE
    peers_grow = p.valid and p.pct > 0
    peers_fall = p.valid and p.pct < 0
    if c.pct < 0 and mk.pct > 0 and (peers_grow or not p.valid):
        return RULE_REL_UNDERPERF
    if c.pct < 0 and mk.pct < 0 and (peers_fall or not p.valid):
        return RULE_SHARED_PRESSURE
    if c.pct >= 0 and c.pct < mk.pct:
        return RULE_GROW_BELOW_MARSH
    if c.pct > mk.pct:
        return RULE_OUTPERFORM
    return RULE_IN_LINE


def adverse_reasons(m: SliceMetrics, rules: Materiality) -> Tuple[str, ...]:
    """Every material adverse comparison, each stated with its basis."""
    out = []
    if m.growth_gap_marsh_pp is not None and m.growth_gap_marsh_pp <= -rules.growth_gap_pp:
        out.append(f"growth {abs(m.growth_gap_marsh_pp):.1f} percentage points below the Marsh book")
    if m.growth_gap_peer_pp is not None and m.growth_gap_peer_pp <= -rules.growth_gap_pp:
        out.append(f"growth {abs(m.growth_gap_peer_pp):.1f} percentage points below the peer average")
    if m.sow_change_pp is not None and m.sow_change_pp <= -rules.sow_loss_pp:
        out.append(f"share of wallet down {abs(m.sow_change_pp):.1f} percentage points")
    return tuple(out)


def strength_reasons(m: SliceMetrics, rules: Materiality) -> Tuple[str, ...]:
    """Relative strength: share at or above the peer average without material decline."""
    if m.sow_cur is None or m.peer.sow_cur is None:
        return ()
    deteriorating = m.sow_change_pp is not None and m.sow_change_pp <= -rules.sow_loss_pp
    if m.sow_cur >= m.peer.sow_cur and not deteriorating:
        return (f"share of wallet {m.sow_cur:.1f}% vs peer average {m.peer.sow_cur:.1f}%",)
    return ()


def survey_rule(adverse: bool, line: Optional[ScoreLine], rules: Materiality,
                scale_max: float) -> Optional[str]:
    """Commercial weakness read against the survey: both weak, or survey strong."""
    if not adverse or line is None or line.score is None:
        return None
    threshold = rules.survey_gap_points * (scale_max / 5.0)
    weak = ((line.peer_gap is not None and line.peer_gap <= -threshold)
            or (line.movement is not None and line.movement <= -threshold))
    return RULE_SURVEY_WEAK_TOO if weak else RULE_SURVEY_STRONG


def classify(m: SliceMetrics, rules: Materiality, *, is_leader: bool = False,
             survey_line: Optional[ScoreLine] = None, scale_max: float = 5.0) -> Classification:
    adverse = adverse_reasons(m, rules)
    strong = strength_reasons(m, rules)
    labels = tuple(l for l, on in ((LEADER, is_leader), (STRENGTH, bool(strong)),
                                   (ATTENTION, bool(adverse))) if on)
    severity = (SEVERITY_ATTENTION if adverse else
                SEVERITY_STRENGTH if strong or is_leader else SEVERITY_NEUTRAL)
    return Classification(labels=labels, pattern=pattern_of(m), severity=severity,
                          reasons=adverse + strong,
                          survey_rule=survey_rule(bool(adverse), survey_line, rules, scale_max))


def adversity_score(m: SliceMetrics) -> float:
    """How adverse a slice is, for ordering weak products/countries (bigger = worse).

    The most negative of its growth gaps and its share change, weighted by its size so a
    tiny line does not outrank a material one (design Section 18: numeric materiality).
    """
    gaps = [g for g in (m.growth_gap_marsh_pp, m.growth_gap_peer_pp, m.sow_change_pp)
            if g is not None]
    worst = -min(gaps) if gaps else 0.0
    return max(worst, 0.0) * (m.marsh_cur ** 0.5 if m.marsh_cur > 0 else 0.0)
