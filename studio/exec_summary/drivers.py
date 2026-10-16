"""Who moved — the named drivers behind a total (what turns figures into a story).

A summary that says "premium grew 25.8%" and stops is a read-out. An executive needs the
next sentence: WHICH product carried it, how its rank and share moved, and WHICH industry
inside that product did the work — and the same for what held it back. This module ranks
those movers deterministically from metrics already computed; it never invents a cause,
it only decomposes the change into named, measured parts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from studio.exec_summary.config import Materiality
from studio.exec_summary.cube import UNMAPPED
from studio.exec_summary.metrics import SliceMetrics

UP = "up"
DOWN = "down"


@dataclass
class Mover:
    """One named part of a change: a product, an industry within it, or a country."""

    name: str
    metrics: SliceMetrics
    direction: str                      # UP: added premium / outgrew the book; DOWN: the drag
    evidence: Dict[str, str] = field(default_factory=dict)
    contribution: Optional[float] = None   # % of the parent's change, same sign only
    within: Optional["Mover"] = None       # the industry that did most of the work inside

    @property
    def change(self) -> float:
        return self.metrics.carrier_cur - self.metrics.carrier_prior


def change_of(m: SliceMetrics) -> float:
    return m.carrier_cur - m.carrier_prior


def contribution(part: float, total: float) -> Optional[float]:
    """A part's share of a total change — only when both move the same way and the part is
    not bigger than the whole (offsetting moves make "3,000% of the change" meaningless)."""
    if total == 0 or part == 0 or (part > 0) != (total > 0):
        return None
    share = 100.0 * part / total
    return share if share <= 100.0 else None


def lagging(m: SliceMetrics, rules: Materiality) -> bool:
    """Premium fell, share fell materially, or growth trailed the Marsh book materially."""
    gap = m.growth_gap_marsh_pp
    return (change_of(m) < 0
            or (m.sow_change_pp is not None and m.sow_change_pp <= -rules.sow_loss_pp)
            or (gap is not None and gap <= -rules.growth_gap_pp))


def growth_leaders(rows: Sequence[SliceMetrics], name_of, n: int) -> List[Mover]:
    """The ``n`` slices that added the most carrier premium (positive change only)."""
    up = sorted((r for r in rows if change_of(r) > 0), key=lambda r: -change_of(r))[:n]
    return [Mover(name_of(r), r, UP) for r in up]


def drags(rows: Sequence[SliceMetrics], name_of, n: int, rules: Materiality,
          exclude: Sequence[str] = ()) -> List[Mover]:
    """The ``n`` worst lagging slices — biggest premium loss first, then biggest share loss."""
    weak = [r for r in rows if lagging(r, rules) and name_of(r) not in exclude]
    weak.sort(key=lambda r: (change_of(r), r.sow_change_pp or 0.0, r.growth_gap_marsh_pp or 0.0))
    return [Mover(name_of(r), r, DOWN) for r in weak[:n]]


def industry_mover(rows: Sequence[SliceMetrics], direction: str) -> Optional[SliceMetrics]:
    """The SIC major that moved most in ``direction`` inside one product (Unmapped excluded)."""
    valid = [r for r in rows if r.scope.industry not in (None, UNMAPPED) and change_of(r) != 0]
    if direction == UP:
        valid = [r for r in valid if change_of(r) > 0]
        return max(valid, key=change_of, default=None)
    valid = [r for r in valid if change_of(r) < 0]
    return min(valid, key=change_of, default=None)
