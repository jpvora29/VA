"""What drove the movement — decomposed from the rows, not asked of a model.

"Premium fell $2.7m" is the finding. "Property is $3.1m of that fall, and Cyber
offset $0.4m of it" is the analysis, and it is the next thing an analyst does
every single time. It is also arithmetic: which slice moved, by how much, and
what share of the total move each one accounts for.

So it is computed here, from the rows the answer was already written from. Two
consequences, both deliberate:

* it is instant and free — no second query, no model call; and
* it CANNOT disagree with the answer above it, because it is the same rows.

A share of the move can exceed 100% and can be negative. That is not an error:
when one slice falls further than the total, another slice grew to offset it,
and hiding that would hide the actual story. Both are reported as they are.

Pure: rows in, a :class:`Contribution` out, and a `note` when the rows cannot
support one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Column-role patterns. Deliberately NOT shared with the boardroom's signal
# detection, which answers a different question ("does this data support widget
# X?"); merging them would couple two things that only happen to look alike.
PERIOD_COLUMN = re.compile(r"(?i)^(.*_)?(year|quarter|qtr|month|period|date)(_.*)?$")
MEASURE_COLUMN = re.compile(
    r"(?i)premium|gwp|amount|value|revenue|score|nps|total|sum|count|share|sow"
)
# Never a measure, even when it holds numbers: an id is a label and a year is an
# axis. Summing either produces a number that means nothing.
NOT_A_MEASURE = re.compile(r"(?i)(^|_)(id|code|rank|year|quarter|month)(_|$)")


@dataclass(frozen=True)
class Driver:
    """One slice's part in the movement."""

    name: str
    prior: float
    current: float

    @property
    def delta(self) -> float:
        return self.current - self.prior

    def share_of(self, total_move: float) -> Optional[float]:
        """This slice's share of the total movement, as a percentage."""
        if not total_move:
            return None
        return round(self.delta / total_move * 100.0, 1)


@dataclass(frozen=True)
class Contribution:
    """The decomposition, or the honest reason there isn't one."""

    measure: str = ""
    dimension: str = ""
    period_column: str = ""
    prior_period: str = ""
    current_period: str = ""
    drivers: List[Driver] = field(default_factory=list)
    note: str = ""

    @property
    def prior_total(self) -> float:
        return sum(d.prior for d in self.drivers)

    @property
    def current_total(self) -> float:
        return sum(d.current for d in self.drivers)

    @property
    def total_move(self) -> float:
        return self.current_total - self.prior_total

    @property
    def is_supported(self) -> bool:
        return bool(self.drivers)

    @property
    def movers(self) -> List[Driver]:
        """The slices that actually moved, biggest first."""
        return [d for d in self.drivers if d.delta]

    @property
    def against(self) -> List[Driver]:
        """The slices that moved AGAINST the total — the offset, if there is one."""
        if not self.total_move:
            return []
        return [d for d in self.movers if (d.delta > 0) != (self.total_move > 0)]

    def headline(self) -> str:
        """The finding in one sentence, before any chart.

        A panel that opens with a chart makes the reader derive the conclusion
        from it. The conclusion is one sentence and it is computable, so it is
        computed: which slice carried the movement, and what offset it.
        """
        movers = self.movers
        if not movers:
            return "Nothing moved between these periods."
        lead = movers[0]
        share = lead.share_of(self.total_move)
        of_move = f" — {abs(share):.0f}% of the movement" if share is not None else ""
        sentence = f"{lead.name} {'fell' if lead.delta < 0 else 'grew'} the most{of_move}."
        offsets = self.against
        if offsets:
            names = " and ".join(d.name for d in offsets[:2])
            # The noun, not the verb: "held the fall back", never "held the fell
            # back". Which way the total went decides the word.
            noun = "fall" if self.total_move < 0 else "rise"
            sentence += f" {names} moved the other way, holding the overall {noun} back."
        return sentence

    @property
    def dimension_label(self) -> str:
        """The slice's name as a person says it: `Product_Line` -> "Product line"."""
        text = str(self.dimension or "").replace("_", " ").strip()
        return (text[:1].upper() + text[1:]) if text else "Slice"

    def as_dict(self) -> Dict[str, Any]:
        move = self.total_move
        return {
            "headline": self.headline(),
            "dimension_label": self.dimension_label,
            "measure": self.measure,
            "dimension": self.dimension,
            "period_column": self.period_column,
            "prior_period": self.prior_period,
            "current_period": self.current_period,
            "prior_total": self.prior_total,
            "current_total": self.current_total,
            "total_move": move,
            "note": self.note,
            "drivers": [
                {
                    "name": d.name,
                    "prior": d.prior,
                    "current": d.current,
                    "delta": d.delta,
                    "share_pct": d.share_of(move),
                }
                for d in self.drivers
            ],
        }


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _columns(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    return list(rows[0].keys()) if rows and isinstance(rows[0], Mapping) else []


def _distinct(rows: Sequence[Mapping[str, Any]], column: str) -> List[str]:
    seen: List[str] = []
    for row in rows:
        value = str(row.get(column, "")).strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def find_period_column(rows: Sequence[Mapping[str, Any]]) -> str:
    """The column holding the comparison, or "" when the rows span one period.

    It must have at least two distinct values — a period column pinned to a
    single year is a filter that came back in the SELECT, not a comparison.
    """
    for column in _columns(rows):
        if PERIOD_COLUMN.match(str(column)) and len(_distinct(rows, column)) >= 2:
            return str(column)
    return ""


def find_measure_column(rows: Sequence[Mapping[str, Any]], exclude: Sequence[str] = ()) -> str:
    """The numeric column being decomposed.

    A named measure wins over a merely-numeric column, so a result carrying both
    `Premium` and `Policy_Count` decomposes the premium — which is what the
    question was about.
    """
    numeric = [
        c
        for c in _columns(rows)
        if c not in exclude
        and not NOT_A_MEASURE.search(str(c))
        and any(_number(r.get(c)) is not None for r in rows)
    ]
    named = [c for c in numeric if MEASURE_COLUMN.search(str(c))]
    return str((named or numeric or [""])[0])


def find_dimension_column(
    rows: Sequence[Mapping[str, Any]], exclude: Sequence[str] = ()
) -> str:
    """The slice to decompose BY — the categorical column with real variety."""
    best, best_count = "", 1
    for column in _columns(rows):
        if column in exclude or PERIOD_COLUMN.match(str(column)):
            continue
        # A measure is not a slice. Without this the premium column itself wins
        # the count and the movement gets "attributed" to its own values.
        if any(_number(row.get(column)) is not None for row in rows):
            continue
        values = _distinct(rows, column)
        # A column whose every row is a different value is an id, not a slice.
        if 1 < len(values) < max(2, len(rows)) and len(values) > best_count:
            best, best_count = str(column), len(values)
    return best


def order_periods(values: Sequence[str]) -> List[str]:
    """Period labels oldest first, so "Q1 2026" comes before "Q2 2026".

    Length before value, because a shorter label sorts as an earlier one for the
    formats this data uses ("2024" before "2024 Q1"), and a plain lexical sort
    would put "Q10" before "Q2".
    """
    return sorted(values, key=lambda v: (len(v), v))


def _ordered_periods(values: Sequence[str]) -> Tuple[str, str]:
    """(prior, current) — the last two, oldest first."""
    ordered = order_periods(values)
    return ordered[-2], ordered[-1]


def decompose(rows: Sequence[Mapping[str, Any]]) -> Contribution:
    """Break the movement between the last two periods down by slice.

    Returns a `Contribution` carrying a `note` — never raises, and never invents
    a comparison the rows do not contain.
    """
    rows = [r for r in rows or [] if isinstance(r, Mapping)]
    if not rows:
        return Contribution(note="There are no rows behind this answer to break down.")

    period = find_period_column(rows)
    if not period:
        return Contribution(
            note="These rows cover one period, so there is no movement to break down."
        )
    prior, current = _ordered_periods(_distinct(rows, period))

    dimension = find_dimension_column(rows, exclude=[period])
    if not dimension:
        return Contribution(
            note="These rows are not split by any dimension, so the movement cannot be attributed."
        )

    measure = find_measure_column(rows, exclude=[period, dimension])
    if not measure:
        return Contribution(note="These rows carry no measure to decompose.")

    totals: Dict[str, Dict[str, float]] = {}
    for row in rows:
        bucket = str(row.get(period, "")).strip()
        if bucket not in (prior, current):
            continue
        value = _number(row.get(measure))
        if value is None:
            continue
        slice_name = str(row.get(dimension, "")).strip() or "(not stated)"
        side = "prior" if bucket == prior else "current"
        totals.setdefault(slice_name, {"prior": 0.0, "current": 0.0})[side] += value

    drivers = [
        Driver(name=name, prior=values["prior"], current=values["current"])
        for name, values in totals.items()
    ]
    if not drivers:
        return Contribution(note="No comparable figures were found for the two periods.")

    # Biggest mover first, in either direction: the slice that explains most of
    # the movement leads, whether it caused the fall or offset it.
    drivers.sort(key=lambda d: abs(d.delta), reverse=True)
    return Contribution(
        measure=measure,
        dimension=dimension,
        period_column=period,
        prior_period=prior,
        current_period=current,
        drivers=drivers,
    )
