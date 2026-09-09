"""What changed unexpectedly — as opposed to what changed most.

A waterfall ranks by size, so the biggest part of the book tops it every single
time. That is true and it is not news: Property leads the movement because
Property leads the book. The reader who comes back every quarter already knows
which slices are large, and a panel that only ever tells them that is the one
they stop opening.

The interesting question is the other one. Germany may be a rounding error in the
total decline and still be the thing worth a call, because this is its first
contraction in six quarters. That judgement needs HISTORY — at least three
periods — which the two-period comparison the panel is built on does not have.
When the rows carry more, this reads it.

Two signals, both arithmetic and both about a slice measured against ITSELF:

    reversal   it has moved one way for several periods, and has just turned
    outsized   this move is far larger than any move it has made before

Slices that already lead the movement are marked rather than dropped: "the
biggest mover is ALSO out of character" is a stronger finding than either half,
and hiding it would be a different kind of lie than the one this module exists to
fix. The panel decides what to show; this decides what is true.

Silent by design. Fewer than three periods, or a slice with too little history,
produces nothing at all rather than a hedge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

from core.answers.contribution import Contribution, order_periods
from core.answers.language import plural

REVERSAL = "reversal"
OUTSIZED = "outsized"

# Both signals compare the latest move against the ones before it, and one
# earlier move is not a pattern to be out of: "its biggest move ever" off a
# single prior move says only that two numbers differ. Two prior moves is the
# floor, which needs four periods — three deltas, the last judged against two.
_MIN_PRIOR_MOVES = 2
_MIN_PERIODS = _MIN_PRIOR_MOVES + 2

# A reversal is only a story after a RUN. One rise then a fall is noise; three
# rises then a fall is a turn.
_MIN_RUN = _MIN_PRIOR_MOVES

# How much bigger than its own largest previous move a slice has to jump before
# the move is remarkable rather than merely the top of its range.
_OUTSIZED_MULTIPLE = 2.0

# Below this the arithmetic is unstable and the sentence would be silly — a slice
# that moved $200 and now moves $800 is not news.
_OUTSIZED_FLOOR = 1e-9

# The word for one step along the period axis, from the column's own name.
_PERIOD_WORDS = ("quarter", "month", "year", "week", "day")


@dataclass(frozen=True)
class Unusual:
    """One slice whose latest move is out of character, and why."""

    name: str
    delta: float
    kind: str
    reason: str
    is_leader: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "delta": self.delta,
            "kind": self.kind,
            "reason": self.reason,
            "is_leader": self.is_leader,
        }


def period_word(column: str) -> str:
    """"quarter" from `Fiscal_Quarter`, falling back to "period"."""
    name = str(column or "").lower()
    for word in _PERIOD_WORDS:
        if re.search(rf"\b{word}\b", name.replace("_", " ")):
            return word
    return "period"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def series_by_slice(
    rows: Sequence[Mapping[str, Any]], *, period: str, dimension: str, measure: str
) -> Dict[str, List[float]]:
    """Each slice's measure across every period present, oldest first.

    A period a slice has no row for is a hole, not a zero — reading it as zero
    would manufacture a collapse and a recovery that never happened. Such a slice
    is dropped rather than guessed at.
    """
    periods = order_periods(
        [p for p in {str(r.get(period, "")).strip() for r in rows} if p]
    )
    totals: Dict[str, Dict[str, float]] = {}
    for row in rows:
        bucket = str(row.get(period, "")).strip()
        value = _number(row.get(measure))
        if not bucket or value is None:
            continue
        name = str(row.get(dimension, "")).strip() or "(not stated)"
        totals.setdefault(name, {})[bucket] = totals.setdefault(name, {}).get(bucket, 0.0) + value

    out: Dict[str, List[float]] = {}
    for name, by_period in totals.items():
        if any(p not in by_period for p in periods):
            continue
        out[name] = [by_period[p] for p in periods]
    return out


def _deltas(values: Sequence[float]) -> List[float]:
    return [b - a for a, b in zip(values, values[1:])]


def _reversal(deltas: Sequence[float], word: str) -> str:
    """"its first fall in five quarters", when there is a run to break."""
    latest = deltas[-1]
    if not latest:
        return ""
    run = 0
    for earlier in reversed(deltas[:-1]):
        if not earlier or (earlier > 0) == (latest > 0):
            break
        run += 1
    if run < _MIN_RUN:
        return ""
    # `run` prior moves the other way span `run + 1` periods in which this never
    # happened, which is the number a reader counts.
    spanned = run + 1
    direction = "fall" if latest < 0 else "rise"
    return f"its first {direction} in {spanned} {plural(word, spanned)}"


def _outsized(deltas: Sequence[float], word: str) -> str:
    """"more than twice any move it had made before"."""
    latest = deltas[-1]
    earlier = [abs(d) for d in deltas[:-1]]
    biggest = max(earlier, default=0.0)
    if len(earlier) < _MIN_PRIOR_MOVES or biggest <= _OUTSIZED_FLOOR or not latest:
        return ""
    multiple = abs(latest) / biggest
    if multiple < _OUTSIZED_MULTIPLE:
        return ""
    spanned = len(deltas) + 1
    return (
        f"its biggest move in {spanned} {plural(word, spanned)} — "
        f"{multiple:.1f}× the largest before it"
    )


def _judge(name: str, values: Sequence[float], word: str, leaders: Sequence[str]) -> Unusual | None:
    """The one thing worth saying about this slice, or nothing."""
    deltas = _deltas(values)
    if len(deltas) <= _MIN_PRIOR_MOVES:
        return None
    latest = deltas[-1]
    # A reversal is the stronger reading when both apply: "it has turned" says
    # more than "it moved a lot", and two sentences about one slice is a list.
    reason = _reversal(deltas, word)
    kind = REVERSAL
    if not reason:
        reason, kind = _outsized(deltas, word), OUTSIZED
    if not reason:
        return None
    return Unusual(name=name, delta=latest, kind=kind, reason=reason, is_leader=name in leaders)


def find_unusual(
    rows: Sequence[Mapping[str, Any]],
    contribution: Contribution,
    *,
    already_told: Sequence[str] = (),
    limit: int = 3,
) -> List[Unusual]:
    """The slices whose latest move is out of character, most notable first.

    `already_told` is the slices the panel's lead sentence names — pass
    `Profile.leaders`. It decides the ORDER, not what is included: a slice the
    reader has just read about is still worth flagging as out of character, but
    it goes below the one they have not, because "small, but it has just turned"
    is the finding the ranking hides. Deriving "leader" here instead would mean
    two definitions of the same idea, and with only three slices a plain top-two
    makes everything a leader.

    Never raises; returns [] whenever the rows cannot support the judgement.
    """
    rows = [r for r in rows or [] if isinstance(r, Mapping)]
    if not rows or not contribution.is_supported or not contribution.period_column:
        return []

    series = series_by_slice(
        rows,
        period=contribution.period_column,
        dimension=contribution.dimension,
        measure=contribution.measure,
    )
    if not series or max(len(v) for v in series.values()) < _MIN_PERIODS:
        return []

    word = period_word(contribution.period_column)
    leaders = [str(name) for name in already_told]
    found = [
        judged
        for name, values in series.items()
        if len(values) >= _MIN_PERIODS
        for judged in [_judge(name, values, word, leaders)]
        if judged is not None
    ]
    found.sort(key=lambda u: (u.is_leader, -abs(u.delta)))
    return found[:limit]
