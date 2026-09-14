"""Decomposing a year-on-year movement into the parts that explain it.

Three calculations the library did not previously have, and which a performance
answer cannot be written without:

  ``compute_aligned_periods``  each quarter against the SAME quarter a year
                               earlier, so the TIMING of a movement is visible
  ``compute_contribution``     each slice's share of the headline change, in
                               points of the prior total, including offsets
  ``reconcile``                whether a decomposition adds back up, and what is
                               left over when it does not

What was already there and is NOT this: `compute_yoy` gives a percentage per
slice, which ranks small slices above large ones and cannot be summed;
`compute_period_change` compares each period with the one BEFORE it, so it
reports Q1 against the preceding Q4 and says nothing about the year-on-year gap;
`compute_yoy_to_date` collapses a whole year into one truncated figure.

Three rules the plan is explicit about, enforced here rather than in a prompt:

  * a contribution is NOT clamped. One product can be worse than the net change
    when another grew, and clamping it to the headline erases the offset — the
    single most useful thing a decomposition has to say.
  * a percentage is computed only where the denominator supports it. A zero
    prior value yields an absolute change and no percentage — never an infinity,
    never a silent zero, never a "new" slice reported as flat.
  * an incomplete decomposition reports its residual. A product split covering
    90% of a movement is useful; one that claims completeness it does not have
    is worse than nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.analytics import pandas_library as P
from core.analytics.frames import on_frames
from core.analytics.periods import (
    period_in_year_expr,
    period_label,
    without_period_filters,
    year_expr,
)
from core.analytics.sql import (
    flow_spec,
    resolve_engine,
    resolve_measure,
    run_rows,
    safe_column,
    where_clause,
)
from core.analytics.types import AnalyticsFact, PrimitiveArgs

#: Rounding for a quoted percentage. One decimal is what the writer renders.
PERCENT_PLACES = 1

#: A decomposition this close to the headline counts as reconciling. Float sums
#: over many rows do not land exactly, and demanding exactness would report a
#: residual on a cut that is in fact complete.
RECONCILE_TOLERANCE = 1e-6

#: What a slice's presence across the two years says about it.
PRESENT = "both"
NEW = "current_only"
LAPSED = "prior_only"


def _num(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _cuts(spec, group_by: Sequence[str]) -> List[str]:
    return [safe_column(spec, column) for column in group_by]


# --------------------------------------------------------------------------- #
# Pure arithmetic
# --------------------------------------------------------------------------- #


def percent_change(current: float, prior: float) -> Optional[float]:
    """Percentage change, or None where the denominator cannot carry one.

    None is the honest answer for a slice that did not exist last year.
    Returning 0.0 would read as "flat"; returning a large number would read as
    growth from a base that was never there.
    """
    if prior == 0:
        return None
    return round((current - prior) / prior * 100, PERCENT_PLACES)


def contribution_points(change: float, prior_total: float) -> Optional[float]:
    """A slice's change as points of the PRIOR TOTAL — additive across slices.

    This is the figure that CAN be summed, which is the whole reason it exists:
    per-slice percentages cannot be, and adding them is the arithmetic error the
    plan calls out by name.
    """
    if prior_total == 0:
        return None
    return round(change / prior_total * 100, PERCENT_PLACES)


def presence(current: float, prior: float) -> str:
    """Whether a slice ran in both years, arrived, or lapsed."""
    if prior == 0 and current != 0:
        return NEW
    if current == 0 and prior != 0:
        return LAPSED
    return PRESENT


@dataclass(frozen=True)
class Reconciliation:
    """Whether the parts of a decomposition add back up to the whole."""

    headline: float
    covered: float
    parts: int

    @property
    def residual(self) -> float:
        return self.headline - self.covered

    @property
    def is_complete(self) -> bool:
        return abs(self.residual) <= max(
            RECONCILE_TOLERANCE, abs(self.headline) * RECONCILE_TOLERANCE
        )

    @property
    def coverage_percent(self) -> Optional[float]:
        if self.headline == 0:
            return None
        return round(self.covered / self.headline * 100, PERCENT_PLACES)

    def limitation(self, cut: str = "") -> str:
        """The sentence to publish when the cut does not fully explain the whole."""
        if self.is_complete:
            return ""
        label = f"The {cut} split" if cut else "This split"
        return (
            f"{label} accounts for {self.covered:,.1f} of a {self.headline:,.1f} "
            f"movement; {self.residual:,.1f} is not attributed."
        )


def reconcile(changes: Sequence[float], headline: float) -> Reconciliation:
    """Compare the summed parts against the whole they claim to explain."""
    return Reconciliation(headline=headline, covered=sum(changes), parts=len(changes))


# --------------------------------------------------------------------------- #
# Corresponding-period comparison
# --------------------------------------------------------------------------- #


@on_frames(P.compute_aligned_periods)
def compute_aligned_periods(
    args: PrimitiveArgs,
    *,
    engine: Optional[Any] = None,
    grain: str = "quarter",
    current_year: Optional[int] = None,
    prior_year: Optional[int] = None,
) -> List[AnalyticsFact]:
    """Each period position of one year against the SAME position a year earlier.

    Q1 2025 against Q1 2024, Q2 against Q2, and so on. Emits one fact per period
    position present in EITHER year, so a quarter that exists in only one of them
    surfaces as a coverage gap rather than vanishing — a missing quarter is not a
    zero, and the distinction is the difference between "no data yet" and "the
    book stopped".

    Period filters are dropped from the scope for the reason they are everywhere
    else here: the comparison needs both years, so a turn pinned to one of them
    would have nothing to compare against. Every non-period filter survives.
    """
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric)
    year_sql, pin_sql = year_expr(spec), period_in_year_expr(spec, grain)
    if year_sql is None or pin_sql is None:
        return []

    cuts = _cuts(spec, args.group_by)
    rows = _period_rows(spec, eng, args, cuts, year_sql, pin_sql, column, agg)
    return assemble_aligned(
        rows, cuts=cuts, column=column, grain=grain,
        current_year=current_year, prior_year=prior_year,
    )


def assemble_aligned(
    rows: Sequence[Mapping[str, Any]],
    *,
    cuts: Sequence[str],
    column: str,
    grain: str = "quarter",
    current_year: Optional[int] = None,
    prior_year: Optional[int] = None,
) -> List[AnalyticsFact]:
    """Build the aligned-period facts from ``{yr, pin, *cuts, measure}`` rows.

    Shared by both executors. The SQL primitive above and the pandas twin in
    `core.analytics.pandas_library` differ only in how they produce these rows;
    everything that decides what a fact SAYS lives here, so the two backends
    cannot drift into giving different answers to the same question.
    """
    rows = [row for row in rows if row.get("pin") is not None]
    if not rows:
        return []
    current, prior = resolve_year_pair(rows, current_year, prior_year)
    if current is None or prior is None:
        return []

    measures = _index(rows, cuts, key=lambda row: (int(row["yr"]), int(row["pin"])))
    return [
        aligned_fact(
            column=column,
            grain=grain,
            position=position,
            current_year=current,
            prior_year=prior,
            cuts=cuts,
            cut_values=cut_values,
            current=measures.get((cut_values, (current, position))),
            prior=measures.get((cut_values, (prior, position))),
        )
        for cut_values in _cut_combinations(rows, cuts)
        for position in _positions(rows, cuts, cut_values)
    ]


def aligned_fact(
    *,
    column: str,
    grain: str,
    position: int,
    current_year: int,
    prior_year: int,
    cuts: Sequence[str],
    cut_values: Tuple,
    current: Optional[float],
    prior: Optional[float],
) -> AnalyticsFact:
    """One corresponding-period comparison, carrying what it could not compare.

    `current` / `prior` are None when that year has no row for the position —
    kept distinct from 0.0 all the way into `dims["coverage"]`, because a
    quarter the warehouse has not loaded and a quarter that wrote nothing are
    different findings.
    """
    current_value, prior_value = _num(current), _num(prior)
    change = current_value - prior_value
    covered = current is not None and prior is not None
    label = period_label(grain, position)
    return AnalyticsFact(
        name="aligned_period_change",
        value=change if covered else 0.0,
        unit=column,
        rendered=f"{change:+,.1f}" if covered else "not comparable",
        dims={
            "period": label,
            "grain": grain,
            "position": position,
            "year": current_year,
            "prior_year": prior_year,
            "coverage": PRESENT if covered else (
                NEW if current is not None else LAPSED
            ),
            "comparable": covered,
            "percent": percent_change(current_value, prior_value) if covered else None,
            **{column_name: value for column_name, value in zip(cuts, cut_values)},
        },
        support=[
            {
                "period": label,
                "measure_name": column,
                f"{prior_year}": prior,
                f"{current_year}": current,
            }
        ],
        formula=f"{current_year} {label} - {prior_year} {label}",
    )


# --------------------------------------------------------------------------- #
# Contribution to the headline change
# --------------------------------------------------------------------------- #


@on_frames(P.compute_contribution)
def compute_contribution(
    args: PrimitiveArgs,
    *,
    engine: Optional[Any] = None,
    current_year: Optional[int] = None,
    prior_year: Optional[int] = None,
) -> List[AnalyticsFact]:
    """Each slice's contribution to the headline year-on-year change.

    The first fact is the headline itself (no cut values), so a reader and a
    verifier can both see what the parts are being measured against without
    re-deriving it. The rest are the slices, ordered by the size of their
    contribution — largest mover first, whichever direction it moved, so a
    growing product that offsets a decline is not buried under the losses.
    """
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric)
    year_sql = year_expr(spec)
    if year_sql is None:
        return []

    cuts = _cuts(spec, args.group_by)
    rows = _year_rows(spec, eng, args, cuts, year_sql, column, agg)
    return assemble_contribution(
        rows, cuts=cuts, column=column,
        current_year=current_year, prior_year=prior_year,
    )


def assemble_contribution(
    rows: Sequence[Mapping[str, Any]],
    *,
    cuts: Sequence[str],
    column: str,
    current_year: Optional[int] = None,
    prior_year: Optional[int] = None,
) -> List[AnalyticsFact]:
    """Build the headline and contribution facts from ``{yr, *cuts, measure}`` rows.

    Shared by both executors, for the reason given on `assemble_aligned`.
    """
    rows = [row for row in rows if row.get("yr") is not None]
    if not rows:
        return []
    current, prior = resolve_year_pair(rows, current_year, prior_year)
    if current is None or prior is None:
        return []

    measures = _index(rows, cuts, key=lambda row: int(row["yr"]))
    prior_total = sum(
        value for (_cut, year), value in measures.items() if year == prior
    )
    current_total = sum(
        value for (_cut, year), value in measures.items() if year == current
    )

    slices = [
        contribution_fact(
            column=column,
            current_year=current,
            prior_year=prior,
            cuts=cuts,
            cut_values=cut_values,
            current=measures.get((cut_values, current), 0.0),
            prior=measures.get((cut_values, prior), 0.0),
            prior_total=prior_total,
        )
        for cut_values in _cut_combinations(rows, cuts)
    ]
    slices.sort(key=lambda fact: abs(fact.value), reverse=True)
    return [headline_fact(column, current, prior, current_total, prior_total)] + slices


def headline_fact(
    column: str, current_year: int, prior_year: int, current: float, prior: float
) -> AnalyticsFact:
    """The whole the parts must add up to."""
    change = current - prior
    return AnalyticsFact(
        name="headline_change",
        value=change,
        unit=column,
        rendered=f"{change:+,.1f}",
        dims={
            "year": current_year,
            "prior_year": prior_year,
            "percent": percent_change(current, prior),
            "scope": "total",
        },
        support=[
            {
                "measure_name": column,
                f"{prior_year}": prior,
                f"{current_year}": current,
            }
        ],
        formula=f"{current_year} total - {prior_year} total",
    )


def contribution_fact(
    *,
    column: str,
    current_year: int,
    prior_year: int,
    cuts: Sequence[str],
    cut_values: Tuple,
    current: float,
    prior: float,
    prior_total: float,
) -> AnalyticsFact:
    """One slice's movement and its share of the headline, unclamped."""
    change = current - prior
    return AnalyticsFact(
        name="contribution",
        value=change,
        unit=column,
        rendered=f"{change:+,.1f}",
        dims={
            "year": current_year,
            "prior_year": prior_year,
            "contribution_pp": contribution_points(change, prior_total),
            "percent": percent_change(current, prior),
            "presence": presence(current, prior),
            **{column_name: value for column_name, value in zip(cuts, cut_values)},
        },
        support=[
            {
                "measure_name": column,
                f"{prior_year}": prior,
                f"{current_year}": current,
                "prior_total": prior_total,
            }
        ],
        formula=(
            f"({current_year} - {prior_year}) for this slice; "
            f"contribution = slice change / {prior_year} total * 100"
        ),
    )


# --------------------------------------------------------------------------- #
# Shared retrieval
# --------------------------------------------------------------------------- #


def _period_rows(spec, engine, args, cuts, year_sql, pin_sql, column, agg):
    params: Dict[str, Any] = {}
    where = where_clause(spec, without_period_filters(spec, args.filters), params)
    cut_tail = ", " + ", ".join(f'"{c}"' for c in cuts) if cuts else ""
    sql = f"""
        SELECT {year_sql} AS yr, {pin_sql} AS pin{cut_tail},
               {agg}("{column}") AS measure
        FROM "{spec.primary_table}"{where}
        GROUP BY yr, pin{cut_tail}
        ORDER BY yr, pin
    """
    return [row for row in run_rows(engine, sql, params) if row.get("pin") is not None]


def _year_rows(spec, engine, args, cuts, year_sql, column, agg):
    params: Dict[str, Any] = {}
    where = where_clause(spec, without_period_filters(spec, args.filters), params)
    cut_tail = ", " + ", ".join(f'"{c}"' for c in cuts) if cuts else ""
    sql = f"""
        SELECT {year_sql} AS yr{cut_tail}, {agg}("{column}") AS measure
        FROM "{spec.primary_table}"{where}
        GROUP BY yr{cut_tail}
        ORDER BY yr
    """
    return [row for row in run_rows(engine, sql, params) if row.get("yr") is not None]


def resolve_year_pair(
    rows: Sequence[Mapping[str, Any]],
    current: Optional[int] = None,
    prior: Optional[int] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """The two years to compare: those asked for, else the latest two present.

    Returns (None, None) rather than a partial answer when a requested year is
    absent or only one year exists — an unanswerable comparison must not
    degrade into a one-year figure presented as a movement.
    """
    years = sorted({int(row["yr"]) for row in rows if row.get("yr") is not None})
    if current is not None or prior is not None:
        if current in years and prior in years:
            return current, prior
        return None, None
    if len(years) < 2:
        return None, None
    return years[-1], years[-2]


def _index(rows, cuts, *, key) -> Dict[Tuple, float]:
    """(cut values, key) -> summed measure."""
    index: Dict[Tuple, float] = {}
    for row in rows:
        entry = (tuple(row[c] for c in cuts), key(row))
        index[entry] = index.get(entry, 0.0) + _num(row["measure"])
    return index


def _cut_combinations(rows, cuts) -> List[Tuple]:
    """Every distinct combination of cut values, in a stable order."""
    if not cuts:
        return [()]
    seen = {tuple(row[c] for c in cuts) for row in rows}
    return sorted(seen, key=lambda values: tuple(str(v) for v in values))


def _positions(rows, cuts, cut_values) -> List[int]:
    """Period positions this cut has in either year, ascending."""
    return sorted(
        {
            int(row["pin"])
            for row in rows
            if tuple(row[c] for c in cuts) == cut_values
        }
    )
