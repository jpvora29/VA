"""What a picked quarter means for the reporting period — pure, no IO.

Setup's Quarter filter does two different jobs depending on the basis:

* **YTD (calendar)** — it narrows the rows to the quarter, so the deck reports "Q2 2026"
  against "Q2 2025" and every slide must say so instead of "FY 2026".
* **R12M** — it does NOT narrow the rows. It anchors the twelve months: R12M with Q2 2026
  is July 2025 to June 2026, and the picker's "Ends" month follows the quarter.

Quarter labels may be year-stamped ("2026 Q2", "Q2-2026"); only the quarter NUMBER matters
here, the year comes from the Year filter.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

QUARTER_COLUMN = "Quarter"
MONTH_NAME_COLUMN = "Month_Name"

_YEAR = re.compile(r"(19|20)\d{2}")
_QUARTER_DIGIT = re.compile(r"[1-4]")
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


def quarter_number(label: Any) -> int | None:
    """1..4 for a quarter label ("Q3", "2026 Q3", "3"), ``None`` for anything else."""
    text = _YEAR.sub("", str(label or ""))
    found = _QUARTER_DIGIT.search(text)
    return int(found.group(0)) if found else None


def picked_quarters(values: Any) -> tuple[int, ...]:
    """The distinct quarter numbers a form value (or list of them) names, in order."""
    items = values if isinstance(values, (list, tuple, set)) else (values,)
    numbers = {quarter_number(v) for v in items} - {None}
    return tuple(sorted(numbers))


def latest_quarter(values: Any) -> int | None:
    """The last quarter picked — what an R12M window ends with."""
    picked = picked_quarters(values)
    return picked[-1] if picked else None


def quarter_end_month(quarter: int) -> int:
    """The last month of ``quarter``: Q1 → 3, Q4 → 12."""
    return int(quarter) * 3


def quarter_anchor(
    year: int,
    quarter: int,
    latest: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """``(year, month)`` an R12M window ends in for ``quarter`` of ``year``.

    Never later than the latest month in the data: Q3 2026 on a book that runs to August
    2026 ends in August, not in a September with nothing in it.
    """
    anchor = (int(year), quarter_end_month(quarter))
    if latest is not None and anchor > tuple(latest):
        return int(latest[0]), int(latest[1])
    return anchor


def quarter_label(quarters: Iterable[int], year: int) -> str | None:
    """How a slide names the quarters of ``year``: "Q2 2026", "Q1–Q2 2026", "Q1, Q3 2026".

    ``None`` for no quarters or all four — that is the whole year, named as one.
    """
    picked = sorted(set(int(q) for q in quarters))
    if not picked or len(picked) == 4:
        return None
    if len(picked) == 1:
        return f"Q{picked[0]} {year}"
    if picked == list(range(picked[0], picked[-1] + 1)):
        return f"Q{picked[0]}–Q{picked[-1]} {year}"
    return f"{', '.join(f'Q{q}' for q in picked)} {year}"


def quarters_to_date(values: Any) -> Any:
    """A Quarter filter read as YTD: every quarter from Q1 to the last one picked.

    Spelt like the picked label, so the filter still matches the book ("2026 Q2" →
    ["2026 Q1", "2026 Q2"]). Nothing picked leaves the value as it is.
    """
    items = list(values) if isinstance(values, (list, tuple, set)) else [values]
    last = latest_quarter(items)
    if last is None:
        return values
    template = next(str(v) for v in items if quarter_number(v) == last)
    return [_with_quarter(template, q) for q in range(1, last + 1)]


def _with_quarter(label: str, quarter: int) -> str:
    """``label`` with its quarter digit set to ``quarter``; a year in it is left alone."""
    year = _YEAR.search(label)
    for found in _QUARTER_DIGIT.finditer(label):
        if year and year.start() <= found.start() < year.end():
            continue
        return f"{label[: found.start()]}{quarter}{label[found.end() :]}"
    return label


def quarters_in_filters(filters: Mapping[str, Any] | None) -> tuple[int, ...]:
    """The quarters a RESOLVED filter set narrows to (``compute._resolve_filters``).

    The quarter arrives as the book's own ``Quarter`` labels, or — on a book without that
    column — as the month names it covers; months count only when they are exactly whole
    quarters (January–August is a YTD, not "Q1–Q2").
    """
    filters = filters or {}
    if filters.get(QUARTER_COLUMN) not in (None, "", (), []):
        return picked_quarters(filters[QUARTER_COLUMN])
    months = _month_numbers(filters.get(MONTH_NAME_COLUMN))
    quarters = tuple(q for q in range(1, 5) if {3 * q - 2, 3 * q - 1, 3 * q} <= months)
    whole = {m for q in quarters for m in (3 * q - 2, 3 * q - 1, 3 * q)}
    # Months that are not whole quarters (a YTD's January–August) name no quarter.
    return quarters if whole == months else ()


def _month_numbers(values: Any) -> set[int]:
    items = values if isinstance(values, (list, tuple, set)) else (values,)
    found = set()
    for value in items:
        head = str(value or "").strip().lower()[:3]
        if head in _MONTHS:
            found.add(_MONTHS.index(head) + 1)
    return found
