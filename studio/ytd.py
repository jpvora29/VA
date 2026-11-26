"""Like-for-like YTD — the plain YTD compares the same months of both years.

Setup's default (YTD, no ending month picked) used to set the running year against the
WHOLE year before: eight months of 2026 against twelve of 2025, labelled "FY2026". It now
reports 1 January to the latest month of the market's data against the same months a
year earlier, and every page names it "YTD Aug 2026".

Applied as a ``Month_Name`` constraint rather than through the working book's date
window: a run that pins no market reads the warehouse in place (it can be tens of
millions of rows), and a month filter costs one query where a window would cost a copy.

Out of scope, so the result is unchanged:
  * a window is already applied (R12M, an ending month, a date range);
  * a quarter is pinned — the quarter is already the same months of both years;
  * the reporting year is complete, or is not the latest year in the data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from logger import get_logger
from studio import period as P

logger = get_logger(__name__)

YEAR_COLUMN = "Year"
MONTH_COLUMN = "Month_Name"
QUARTER_COLUMN = "Quarter"
CARRIER_COLUMN = "Carrier_Group"

_MONTHS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)


@dataclass(frozen=True)
class YtdScope:
    """The months a like-for-like YTD keeps, as the book spells them, and its window."""

    months: tuple[str, ...]
    window: P.PeriodWindow


def like_for_like_ytd(
    engine: Any,
    flow: str,
    filters: Mapping[str, Any],
    period: P.PeriodWindow | None,
) -> YtdScope | None:
    """The YTD scope for a resolved request, or ``None`` when the plain year stands."""
    if period is not None or _pins_months(filters):
        return None
    rows = _market_months(engine, flow, filters)
    latest = _latest(rows)
    year = P.year_pin(filters.get(YEAR_COLUMN)) or (latest[0] if latest else None)
    window = P.default_ytd_window(year, latest)
    if window is None:
        return None
    months = tuple(
        sorted({label for _y, month, label in rows if month <= window.end.month})
    )
    return YtdScope(months=months, window=window) if months else None


def apply_ytd(filters: dict[str, Any], scope: YtdScope | None) -> dict[str, Any]:
    """``filters`` narrowed to the YTD months (unchanged without a scope)."""
    if scope is None:
        return filters
    return {**filters, MONTH_COLUMN: scope.months}


def is_like_for_like_ytd(
    window: P.PeriodWindow | None, filters: Mapping[str, Any]
) -> bool:
    """Whether ``window`` is the plain YTD this module applied (a month filter, no relabel).

    The Executive Summary names such a period itself ("H1 2026", "9M 2026"), so it must not
    mistake it for an R12M or date-range window that names itself.
    """
    return bool(window is not None and window.is_ytd and filters.get(MONTH_COLUMN))


def _pins_months(filters: Mapping[str, Any]) -> bool:
    return any(
        filters.get(c) not in (None, "", (), []) for c in (QUARTER_COLUMN, MONTH_COLUMN)
    )


def _market_months(
    engine: Any, flow: str, filters: Mapping[str, Any]
) -> list[tuple[int, int, str]]:
    """``(year, month number, stored label)`` for every month the MARKET's data holds.

    The carrier pin and year pin are left out: the period is the market's (a carrier that
    stopped writing in June still reports YTD Aug), and the latest year is part of the answer.
    """
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    market = {
        k: v for k, v in filters.items() if k not in (CARRIER_COLUMN, YEAR_COLUMN)
    }
    try:
        facts = compute_breakdown(
            PrimitiveArgs(
                flow=flow,
                metric="premium",
                group_by=(YEAR_COLUMN, MONTH_COLUMN),
                filters=market,
            ),
            engine=engine,
        )
    except Exception as exc:  # noqa: BLE001 - no month column: the plain year stands
        logger.info("ytd: months unreadable (%s) — reporting whole years", exc)
        return []
    rows = []
    for fact in facts or ():
        label = str(fact.dims.get(MONTH_COLUMN) or "").strip()
        month = _month_number(label)
        year = str(fact.dims.get(YEAR_COLUMN) or "").strip()
        if month and year.isdigit():
            rows.append((int(year), month, label))
    return rows


def _latest(rows: list[tuple[int, int, str]]) -> tuple[int, int] | None:
    return max(((y, m) for y, m, _label in rows), default=None)


def _month_number(label: str) -> int | None:
    head = label.lower()[:3]
    return _MONTHS.index(head) + 1 if head in _MONTHS else None
