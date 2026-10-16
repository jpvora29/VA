"""Whitespace qualification and ranking (design Sections 11 and 12).

Hard gates first, every pass/fail kept on the candidate; then a transparent lexicographic
rank — no opaque score. Whitespace means low carrier participation in a material, growing
Marsh book; it never establishes appetite, capacity or a revenue forecast, which is why
every candidate here is ``conditional`` until fit is validated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from studio.exec_summary.config import WhitespaceGates
from studio.exec_summary.cube import UNMAPPED
from studio.exec_summary.metrics import SliceMetrics

ELIGIBLE = "eligible"            # fit confirmed (no appetite source today, so never set)
CONDITIONAL = "conditional"      # passes the gates; appetite/capacity unvalidated
NEW_BOOK = "new_book"            # zero prior Marsh book — routed separately
EXCLUDED = "excluded"

PATH_EXPAND = "expand_strength"  # Scenario 1
PATH_REBUILD = "rebuild_weak"    # Scenario 2
PATH_DEVELOP = "develop"

VIEW_INDUSTRY = "industry"
VIEW_SEGMENT = "segment"

FIT_QUALIFICATION = "Appetite, licensing and capacity are not yet validated."


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class OpportunityCandidate:
    candidate_id: str
    country: str
    product: str
    view: str
    name: str                     # the SIC major industry or the segment
    path: str
    eligibility: str
    metrics: SliceMetrics
    gates: Tuple[GateResult, ...]
    segment_detail: Optional[str] = None     # where in the industry, when measured
    benchmark_headroom: Optional[float] = None
    qualifications: Tuple[str, ...] = ()
    evidence: Dict[str, str] = field(default_factory=dict)

    @property
    def qualified(self) -> bool:
        return self.eligibility in (ELIGIBLE, CONDITIONAL)

    def ranking_keys(self) -> tuple:
        """Confirmed fit first, Marsh premium ↓, Marsh growth ↓, carrier SoW ↑, id."""
        m = self.metrics
        return (0 if self.eligibility == ELIGIBLE else 1, -m.marsh_cur,
                -(m.marsh_growth.pct or 0.0), m.sow_cur or 0.0, self.candidate_id)


def evaluate_gates(m: SliceMetrics, gates: WhitespaceGates) -> Tuple[GateResult, ...]:
    """Every common qualification gate, each with the figure that decided it."""
    name_ok = all(v not in (UNMAPPED, "", None) for v in (m.scope.industry, m.scope.segment)
                  if v is not None)
    growth_pct = m.marsh_growth.pct
    sow = m.sow_cur if m.sow_cur is not None else 0.0
    return (
        GateResult("valid_mapping", name_ok, "mapped" if name_ok else "Unmapped bucket"),
        GateResult("positive_marsh_book", m.marsh_cur > 0, f"Marsh {m.marsh_cur:,.0f}"),
        GateResult("material_marsh_book", m.marsh_cur >= gates.material_marsh_premium,
                   f"Marsh {m.marsh_cur:,.0f} vs {gates.material_marsh_premium:,.0f}"),
        GateResult("growing_marsh_book",
                   growth_pct is not None and growth_pct >= gates.min_marsh_growth_pct,
                   f"Marsh growth {m.marsh_growth.status} {growth_pct}"),
        GateResult("negligible_carrier_share",
                   sow <= gates.max_carrier_sow_pct and m.carrier_cur <= gates.max_carrier_premium,
                   f"carrier SoW {sow:.2f}% and premium {m.carrier_cur:,.0f}"),
        GateResult("non_negative_carrier_premium", m.carrier_cur >= 0,
                   "accounting review" if m.carrier_cur < 0 else "ok"),
    )


def eligibility_of(m: SliceMetrics, results: Sequence[GateResult]) -> str:
    if m.marsh_prior == 0 and m.marsh_cur > 0:
        return NEW_BOOK
    return CONDITIONAL if all(r.passed for r in results) else EXCLUDED


def benchmark_headroom(m: SliceMetrics) -> Optional[float]:
    """max(0, peer average SoW − carrier SoW) × Marsh slice premium — a static gap to a
    reference, not an expected win (design Section 12, optional)."""
    if m.peer.sow_cur is None or m.sow_cur is None:
        return None
    return max(0.0, (m.peer.sow_cur - m.sow_cur) / 100.0) * m.marsh_cur


def qualify(m: SliceMetrics, *, country: str, product: str, view: str, name: str,
            path: str, gates: WhitespaceGates,
            segment_detail: Optional[str] = None) -> OpportunityCandidate:
    results = evaluate_gates(m, gates)
    eligibility = eligibility_of(m, results)
    quals = [FIT_QUALIFICATION]
    if not m.peer.available:
        quals.append("Peer participation reference unavailable.")
    return OpportunityCandidate(
        candidate_id=m.scope.scope_id, country=country, product=product, view=view,
        name=name, path=path, eligibility=eligibility, metrics=m, gates=results,
        segment_detail=segment_detail, benchmark_headroom=benchmark_headroom(m),
        qualifications=tuple(quals),
    )


def ranked(candidates: Sequence[OpportunityCandidate]) -> List[OpportunityCandidate]:
    """Qualified candidates in rank order; excluded and new-book ones are not ranked."""
    return sorted((c for c in candidates if c.qualified), key=lambda c: c.ranking_keys())


def shortlist(candidates: Sequence[OpportunityCandidate], n: int) -> List[OpportunityCandidate]:
    """The top ``n`` qualified candidates, at most one per (view, name)."""
    seen, out = set(), []
    for c in ranked(candidates):
        if (c.view, c.name) in seen:
            continue
        seen.add((c.view, c.name))
        out.append(c)
        if len(out) == n:
            break
    return out
