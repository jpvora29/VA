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

from typing import Any, Dict, Mapping, Optional

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
