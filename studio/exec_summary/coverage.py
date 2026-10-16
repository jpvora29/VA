"""What part of the year the data actually covers — and a like-for-like comparison.

A book loaded to June is not "FY2026": it is H1 2026, and comparing it with the whole of
2025 would report a fall that is only the missing half-year. So the months the CURRENT
year holds are read off the book, both years are pinned to those same months, and the
period is named for what it is:

    Jan–Mar  -> Q1 2026        Jan–Jun  -> H1 2026        Jan–Sep -> 9M 2026
    Jan–Dec  -> FY2026         Apr–Jun  -> Q2 2026        Jan–May -> YTD May 2026
    anything else            -> "Feb–Apr 2026"

Skipped when the Setup period already relabels the year (R12M, a date range): that window
is a like-for-like period by construction, and it names itself.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

MONTH_COL = "Month_Name"
_ABBR = tuple(calendar.month_abbr)
_NAMES = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_NAMES.update({abbr.lower(): i for i, abbr in enumerate(calendar.month_abbr) if abbr})
_NAMES["sept"] = 9


@dataclass(frozen=True)
class Coverage:
    months: Tuple[int, ...]                 # current-year months present, 1..12
    month_values: Tuple[str, ...] = ()      # the book's own Month_Name values to pin to

    @property
    def full_year(self) -> bool:
        return self.months == tuple(range(1, 13))


def month_number(value: Any) -> Optional[int]:
    """1..12 for "January", "Jan", "1", "01", "2026-01", "2026-01-15" — else ``None``."""
    text = str(value or "").strip().lower()
    if text in _NAMES:
        return _NAMES[text]
    parts = text.replace("/", "-").split("-")
    candidate = parts[1] if len(parts) >= 2 and len(parts[0]) == 4 else parts[0]
    return int(candidate) if candidate.isdigit() and 1 <= int(candidate) <= 12 else None


def period_label(months: Sequence[int], year: int) -> str:
    """How a reader names a span of months in one year."""
    span = tuple(sorted(set(months)))
    if not span or span == tuple(range(1, 13)):
        return f"FY{year}"
    contiguous = span == tuple(range(span[0], span[-1] + 1))
    if contiguous and len(span) == 3 and span[0] in (1, 4, 7, 10):
        return f"Q{(span[0] + 2) // 3} {year}"
    if contiguous and span in (tuple(range(1, 7)), tuple(range(7, 13))):
        return f"{'H1' if span[0] == 1 else 'H2'} {year}"
    if contiguous and span == tuple(range(1, 10)):
        return f"9M {year}"
    if contiguous and span[0] == 1:
        return f"YTD {_ABBR[span[-1]]} {year}"
    if contiguous:
        return f"{_ABBR[span[0]]}–{_ABBR[span[-1]]} {year}"
    return f"{', '.join(_ABBR[m] for m in span)} {year}"


def _month_values(engine: Any, flow: str, filters: Dict[str, Any], year: int) -> Dict[str, int]:
    """``{book value: month number}`` for the months holding premium in ``year``."""
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    facts = compute_breakdown(PrimitiveArgs(flow=flow, metric="premium", group_by=(MONTH_COL,),
                                            filters={**filters, "Year": year}), engine=engine)
    out: Dict[str, int] = {}
    for f in facts:
        raw = f.dims.get(MONTH_COL)
        n = month_number(raw)
        if n is not None and (f.value or 0) != 0:
            out[str(raw)] = n
    return out


def detect_coverage(engine: Any, flow: str, filters: Dict[str, Any], year: int) -> Optional[Coverage]:
    """The current year's months, and the book values that pin BOTH years to them.

    ``None`` when the book has no usable month column (an upload without one): the deck
    then keeps the calendar-year label rather than guessing.
    """
    try:
        current = _month_values(engine, flow, filters, year)
        prior = _month_values(engine, flow, filters, year - 1)
    except Exception as exc:  # noqa: BLE001 — no month column: no partial-year handling
        logger.info("exec_summary.coverage: month coverage unavailable (%s)", exc)
        return None
    months = tuple(sorted(set(current.values())))
    if not months:
        return None
    wanted = set(months)
    values = tuple(sorted({v for v, n in {**prior, **current}.items() if n in wanted}))
    return Coverage(months=months, month_values=values)
