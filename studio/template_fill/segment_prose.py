"""Plain, scoped observations for deterministic segment previews.

Each bullet identifies the segment, carrier metric and comparison. Numeric displays
match commentary evidence. Placement gaps are scenarios, never promised premium.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Set

from studio.segments import OPPORTUNITY_KINDS, Placement, SegmentFinding, SegmentFindings
from studio.template_fill import units as U
from studio.template_fill.render import _money


def _absent(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    return (f"Marsh placed {_money(row.market)} of premium in {row.name}, "
            f"and {subject or 'the carrier'} received none of those placements.")


def _thin(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    return (f"{subject or 'The carrier'} received {row.sow:.1f}% of Marsh's placements in {row.name}, "
            f"below its {row.placed_sow:.1f}% average across the segments it writes. "
            f"Matching that share would correspond to an illustrative {_money(row.stake)} "
            "premium difference at the current Marsh total.")


def _behind(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    from studio.template_fill.commentary_evidence import benchmark_label
    benchmark = benchmark_label({"n_carriers": row.carriers})
    return (f"{subject or 'The carrier'} received {row.sow:.1f}% of Marsh's placements in {row.name}, "
            f"compared with {row.peer_sow:.1f}% for the {benchmark}.")


def _strong(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    return (f"{subject or 'The carrier'} received {row.sow:.1f}% of Marsh's placements in {row.name}, "
            f"above its {row.placed_sow:.1f}% average across the segments it writes.")


def _moved(pct: float) -> str:
    return f"grew {pct:.1f}%" if pct >= 0 else f"fell {abs(pct):.1f}%"


def _losing(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    prior = row.prior_sow if row.prior_sow is not None else row.sow - row.sow_delta
    line = (f"{subject or 'The carrier'}'s share of Marsh's premium in {row.name} fell "
            f"from {prior:.1f}% to {row.sow:.1f}%.")
    if row.market_yoy is not None:
        line += f" Total Marsh-placed premium in that segment {_moved(row.market_yoy)}."
    return line


_SENTENCE: Dict[Placement, Callable[[SegmentFinding, str], str]] = {
    Placement.ABSENT: _absent,
    Placement.THIN: _thin,
    Placement.BEHIND: _behind,
    Placement.STRONG: _strong,
    Placement.LOSING: _losing,
}


def sentence(row: SegmentFinding, subject: str = "", lead: bool = False) -> Optional[str]:
    """One finding as a diagnostic sentence, or ``None`` for a class that says nothing.

    ``lead`` remains accepted for caller compatibility; every observation stands alone.
    """
    build = _SENTENCE.get(row.placement)
    return build(row, subject, lead) if build else None


def _ordered(found: Dict[str, SegmentFindings], kinds: Sequence[Placement],
             ) -> List[SegmentFinding]:
    """Findings of these kinds across every dimension, most premium at stake first.

    Kept in one ranking rather than one per dimension so an industry worth $30M and a client
    segment worth $12M compete on the figure, which is the whole point of ``stake``.
    """
    rows: List[SegmentFinding] = []
    for findings in found.values():
        rows.extend(findings.of(*kinds))
    return sorted(rows, key=lambda r: r.stake, reverse=True)


def points(found: Dict[str, SegmentFindings], *kinds: Placement, subject: str = "",
           limit: int = 3, per_dim: int = 2) -> List[str]:
    """The ranked findings of these kinds as sentences, covering each kind before repeating.

    Ranking on ``stake`` alone lets the richest kind take every slot: a line absent from
    three industries would spend the whole column saying so and never reach the one it
    writes below its own standard. So the first pass takes the strongest finding of EACH
    kind, in the order the kinds argue, and only then fills what is left by premium. A
    column that names an absence, an under-penetration and a peer gap tells a reader three
    different things; one that names three absences tells them one.

    ``per_dim`` stops a single dimension filling the column, so a scope with five absent
    industries still says something about its client segments.
    """
    wanted = tuple(kinds) or OPPORTUNITY_KINDS
    ordered = _ordered(found, wanted)

    first = [next((r for r in ordered if r.placement is kind), None) for kind in wanted]
    rest = [r for r in ordered if r not in first]

    out: List[str] = []
    taken: Dict[str, int] = {}
    led: Set[Placement] = set()
    for row in [r for r in first if r is not None] + rest:
        if len(out) >= limit:
            break
        if taken.get(row.dim, 0) >= per_dim:
            continue
        line = sentence(row, subject, lead=row.placement not in led)
        if not line:
            continue
        led.add(row.placement)
        taken[row.dim] = taken.get(row.dim, 0) + 1
        out.append(line)
    return out


def absence_summary(found: Dict[str, SegmentFindings], subject: str = "") -> Optional[str]:
    """Several absent segments compressed into one line, when naming them all would not fit.

    A scope absent from six industries has one finding, not six, and a column that lists
    them individually spends every bullet on the same point.
    """
    for findings in found.values():
        rows = findings.of(Placement.ABSENT)
        if len(rows) < 2:
            continue
        named = ", ".join(r.name for r in rows[:2])
        rest = len(rows) - 2
        tail = f" and {rest} other {findings.label}" + ("s" if rest != 1 else "") if rest else ""
        return (f"{subject or 'The carrier'} received no Marsh placements across {len(rows)} {findings.label} groups: "
                f"{named}{tail}, together worth {_money(findings.absent_total)} of Marsh "
                f"placements.")
    return None


def tracking_note(label: str = "industry", share: Optional[float] = None) -> str:
    """What a scope that matches its parent says instead of inventing a difference.

    Worth a line: it tells a leadership team there is no local anomaly to chase, which is
    a finding. Manufacturing a difference to fill the column is what the deck did before.
    """
    level = f" Its share of Marsh placements in this scope is {share:.1f}%." if share is not None else ""
    return (f"The carrier's {label} placement pattern tracks the wider portfolio in the "
            f"supplied comparisons.{level}")
