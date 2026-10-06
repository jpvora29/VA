"""Period arithmetic in SQL: years, and positions within a year.

Extracted from `library.py` so that more than one primitive module can build the
same expressions. Nothing here runs a query or knows a business rule — these are
the SQL fragments that turn a flow's declared date columns into a calendar.

The distinction that matters, and the reason two nearly-identical helpers live
side by side:

    period_expr          -> "2025-Q3"   an ABSOLUTE period, ordered across years
    period_in_year_expr  -> 3           a POSITION within its year, 1-4 or 1-12

Sequential period-over-period movement needs the first. Comparing a quarter
against the SAME quarter a year earlier needs the second, and using the first for
that is how Q1 2025 ends up compared with Q4 2024.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from core.analytics.sql import safe_column

QUARTER = "quarter"
MONTH = "month"

PERIODS_PER_YEAR: Mapping[str, int] = {QUARTER: 4, MONTH: 12}


def year_expr(spec) -> Optional[str]:
    """SQL for the calendar year — the declared year column, else read off the date."""
    year = spec.date_columns.get("year")
    if year:
        return f'CAST("{safe_column(spec, year)}" AS INTEGER)'
    date_col = spec.date_columns.get("date")
    if date_col:
        return f"CAST(strftime('%Y', \"{safe_column(spec, date_col)}\") AS INTEGER)"
    return None


def period_expr(spec, grain: str) -> Optional[str]:
    """SQL bucketing the flow's date column into an absolute period label.

    ``month`` -> ``YYYY-MM``; ``quarter`` -> ``YYYY-Qn``. Returns None when the
    flow declares no date column, so callers degrade to "no periodic signal"
    rather than raise.
    """
    date_col = spec.date_columns.get("date")
    if not date_col:
        return None
    safe = safe_column(spec, date_col)
    if grain == MONTH:
        return f"strftime('%Y-%m', \"{safe}\")"
    if grain == QUARTER:
        return (
            f"strftime('%Y', \"{safe}\") || '-Q' || "
            f"CAST((CAST(strftime('%m', \"{safe}\") AS INTEGER) + 2) / 3 AS INTEGER)"
        )
    raise ValueError(f"unknown period grain {grain!r}")


def period_in_year_expr(spec, grain: str) -> Optional[str]:
    """SQL for the period's position WITHIN its year: 1-4 quarterly, 1-12 monthly.

    Prefers a declared quarter column (GIMMI stores ``Quarter``, as "Q2" or 2 —
    the strip handles both), else derives it from the flow's date column. Returns
    None when the flow carries neither, so a year-only flow (the survey has just
    ``Survey_Year``) degrades to "no period alignment" instead of raising.
    """
    quarter = spec.date_columns.get(QUARTER)
    date_col = spec.date_columns.get("date")
    if grain == QUARTER:
        if quarter:
            col = safe_column(spec, quarter)
            return f"CAST(replace(replace(\"{col}\", 'Q', ''), 'q', '') AS INTEGER)"
        if date_col:
            col = safe_column(spec, date_col)
            return f"((CAST(strftime('%m', \"{col}\") AS INTEGER) + 2) / 3)"
        return None
    if grain == MONTH:
        if date_col:
            col = safe_column(spec, date_col)
            return f"CAST(strftime('%m', \"{col}\") AS INTEGER)"
        return None
    raise ValueError(f"unknown period grain {grain!r}")


def period_label(grain: str, position: Any) -> str:
    """``2`` -> "Q2" (quarterly) or "M02" (monthly). Empty on an unusable value."""
    try:
        number = int(position)
    except (TypeError, ValueError):
        return ""
    return f"Q{number}" if grain == QUARTER else f"M{number:02d}"


def period_columns(spec) -> frozenset:
    """Every column that pins the query to a period."""
    return frozenset(
        str(col) for col in (spec.date_columns or {}).values() if col
    )


def without_period_filters(spec, filters: Mapping[str, Any]) -> Dict[str, Any]:
    """`filters` with every period filter removed.

    A comparison needs both sides, so a turn pinned to one year has nothing left
    to compare against. Dropping the pin is not ignoring the user's scope — the
    comparison is *about* the periods, and the non-period filters all survive.
    """
    period = period_columns(spec)
    return {key: value for key, value in (filters or {}).items() if key not in period}


# ── Like-for-like years ─────────────────────────────────────────────────────
#
# The latest year is often loaded part-way. Comparing its months against the
# WHOLE prior year reads a flat book through May as -58%. Every year-on-year
# comparison therefore cuts the prior year to the span the compared year
# reaches: January-May against January-May, Q1-Q2 against Q1-Q2.

def to_date_grain(spec) -> str:
    """The finest within-year grain the flow can align on: month from a date
    column, else quarter from a quarter column, else "" (year-only)."""
    columns = spec.date_columns or {}
    if columns.get("date"):
        return MONTH
    if columns.get(QUARTER):
        return QUARTER
    return ""


def like_for_like_cutoff(rows: Iterable[Mapping[str, Any]], current_year: int,
                         grain: str) -> Optional[int]:
    """The last period the compared year reaches, or None when it is complete
    (or carries no period positions, so there is nothing to align on)."""
    reached = [int(row["pin"]) for row in rows
               if row.get("pin") is not None and row.get("yr") is not None
               and int(row["yr"]) == int(current_year)]
    if not reached or not grain:
        return None
    cutoff = max(reached)
    return None if cutoff >= PERIODS_PER_YEAR.get(grain, 0) else cutoff


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def span_label(grain: str, cutoff: Optional[int]) -> str:
    """"Jan-May" / "Q1-Q2" for a cut year; "" for a whole one."""
    if not cutoff:
        return ""
    if grain == MONTH:
        return "Jan" if cutoff == 1 else f"Jan-{_MONTHS[cutoff - 1]}"
    return "Q1" if cutoff == 1 else f"Q1-Q{cutoff}"


#: The filter key a `PeriodsThrough` travels under. Not a column: `where_clause`
#: and the pandas twin recognise the VALUE, so no schema check applies to it.
THROUGH_KEY = "__periods_through"


@dataclass(frozen=True)
class PeriodsThrough:
    """A filter keeping only the periods of a year up to ``last`` (inclusive).

    Applied to the PRIOR year of a comparison, so it covers the same span the
    current year reaches.
    """

    grain: str
    last: int

    def __str__(self) -> str:
        return span_label(self.grain, self.last)

    def sql(self, spec) -> Optional[str]:
        expr = period_in_year_expr(spec, self.grain)
        return None if expr is None else f"{expr} <= {int(self.last)}"
