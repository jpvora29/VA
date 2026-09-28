"""Which quarters the data actually holds for the market and year Setup has picked.

Setup used to offer Q1–Q4 whatever was selected, so a year that is still running (or a
carrier that only wrote in two quarters) offered quarters with nothing in them. The
quarter list now follows Region, Country, Carrier and Year.

The quarter is still not part of the filter cube (see ``studio.compute.QUARTER_COLUMN``):
the book is read ONCE into distinct ``(scope columns…, quarter)`` rows — cached with the
period profile for the warehouse, derived from the frame for an uploaded dataset — and
this module answers from those rows. Pure: rows in, labels out.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

# What the quarter list follows — the columns a quarter's availability is narrowed by.
SCOPE_COLUMNS: Tuple[str, ...] = ("Region", "Country", "Carrier_Group", "Year")

_BLANK = (None, "", "all", "All")


def _norm(value: Any) -> str:
    """One spelling for a value from SQL, pandas or the form (2025, "2025", 2025.0)."""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def _wanted(value: Any) -> Optional[set]:
    """The accepted spellings for one filter, or ``None`` when it does not constrain."""
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    kept = {_norm(v).lower() for v in values if v not in _BLANK}
    return kept or None


def quarter_label(value: Any, *, native: bool) -> Optional[str]:
    """A book's own ``Quarter`` label as it is, or a quarter NUMBER as ``"Q3"``."""
    if value is None or _norm(value) in ("", "nan", "None"):
        return None
    if native:
        return _norm(value)
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return f"Q{number}" if 1 <= number <= 4 else None


def quarters_in(rows: Iterable[Sequence[Any]], columns: Sequence[str],
                where: Mapping[str, Any]) -> List[str]:
    """The distinct quarter labels (each row's LAST value) of the rows ``where`` allows.

    ``columns`` names the leading values of every row; a filter on a column the rows do
    not carry cannot narrow them and is ignored.
    """
    tests = [(i, wanted) for i, column in enumerate(columns)
             if (wanted := _wanted(where.get(column))) is not None]
    found = {str(row[-1]) for row in rows
             if row[-1] not in (None, "")
             and all(_norm(row[i]).lower() in wanted for i, wanted in tests)}
    return sorted(found)


def frame_quarter_rows(frame) -> Tuple[Tuple[str, ...], List[Tuple[Any, ...]]]:
    """``(scope columns, distinct rows)`` of an uploaded dataset's frame.

    The quarter comes from the frame's own ``Quarter`` column, else its ``Month_Name``,
    else its ``Billing_Date``; a frame with none of those has no quarters to offer.
    """
    import pandas as pd

    from studio.compute import QUARTER_MONTHS

    columns = tuple(c for c in SCOPE_COLUMNS if c in frame.columns)
    if "Quarter" in frame.columns:
        quarter = frame["Quarter"].map(lambda v: quarter_label(v, native=True))
    elif "Month_Name" in frame.columns:
        by_month = {m.lower(): q for q, months in QUARTER_MONTHS.items() for m in months}
        quarter = frame["Month_Name"].map(lambda v: by_month.get(str(v).strip().lower()))
    elif "Billing_Date" in frame.columns:
        dates = pd.to_datetime(frame["Billing_Date"], errors="coerce")
        quarter = dates.dt.quarter.map(lambda v: quarter_label(v, native=False))
    else:
        return columns, []
    table = frame[list(columns)].copy()
    table["__quarter"] = quarter
    table = table.dropna(subset=["__quarter"]).drop_duplicates()
    return columns, [tuple(row) for row in table.itertuples(index=False, name=None)]
