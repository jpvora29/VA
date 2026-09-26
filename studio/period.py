"""The reporting period — calendar year, rolling twelve months (R12M/TTM), or a date range.

Every figure in a deck is "this period against the one a year before": premium, share of
wallet, share of portfolio, rank, the peer benchmark, YoY. The compute layer expresses that
as a YEAR — it pins ``Year = cur`` and compares with ``Year = cur - 1`` — and dozens of call
sites do exactly that. So a new period basis is not a new code path through all of them. It
is a different answer to "which rows belong to year Y":

    calendar   Y = the calendar year                               (the book as stored)
    R12M       Y = the twelve months ending in the anchor month of Y   ("TTM Aug 2026")
    range      Y = the author's own window, ending in Y; Y-1 = the same window a year before

A window no longer than a year repeats yearly without overlapping, so every row belongs to
at most one period year, and relabelling ``Year`` to that period year makes every existing
year comparison mean "this period against the same period a year earlier". That relabelling
is done ONCE, when the run's working book is built (:mod:`studio.book`) — which is why no
metric had to change to honour the toggle.

A range longer than a year cannot repeat without overlapping, so it only restricts the rows
(``RESTRICT``) and years keep their calendar meaning inside it.

Pure: dates and numbers in, windows, labels and SQL fragments out. No IO.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional, Sequence, Tuple

BASIS_CALENDAR = "calendar"
BASIS_R12M = "r12m"
BASES = (BASIS_CALENDAR, BASIS_R12M)

# What a window does to the book.
KIND_R12M = "r12m"          # twelve months ending in the anchor month, relabelled
KIND_RANGE = "range"        # the author's own window (<= 1 year), relabelled
KIND_RESTRICT = "restrict"  # a range longer than a year: rows outside it are dropped

MONTH_ABBR = tuple(calendar.month_abbr)          # ("", "Jan", … "Dec")


# ── what the author chose ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PeriodChoice:
    """The Setup form's period answers, as the selection carries them."""

    basis: str = BASIS_CALENDAR
    date_from: Optional[date] = None
    date_to: Optional[date] = None

    @property
    def is_default(self) -> bool:
        """Calendar year and no dates — the book is used exactly as stored."""
        return self.basis != BASIS_R12M and self.date_from is None and self.date_to is None


def _as_date(value: Any) -> Optional[date]:
    """An ISO date (or the date part of an ISO datetime) — ``None`` for anything else."""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def period_choice(selection: Optional[Mapping[str, Any]]) -> PeriodChoice:
    """The choice a selection carries (``period_basis``, ``date_from``, ``date_to``).

    Missing or unreadable values fall back to the calendar year, so a selection saved
    before the toggle existed builds exactly the deck it always built.
    """
    sel = selection or {}
    basis = str(sel.get("period_basis") or BASIS_CALENDAR).strip().lower()
    start, end = _as_date(sel.get("date_from")), _as_date(sel.get("date_to"))
    if start and end and start > end:
        start, end = end, start
    return PeriodChoice(basis=basis if basis in BASES else BASIS_CALENDAR,
                        date_from=start, date_to=end)


# ── the window it resolves to ────────────────────────────────────────────────


@dataclass(frozen=True)
class PeriodWindow:
    """The current reporting period as a date window (both ends inclusive)."""

    start: date
    end: date
    kind: str = KIND_R12M

    @property
    def year(self) -> int:
        """The period year the window is labelled with — the year it ends in."""
        return self.end.year

    @property
    def relabels(self) -> bool:
        """Whether ``Year`` in the working book means "period year" rather than calendar."""
        return self.kind in (KIND_R12M, KIND_RANGE)

    @property
    def crosses_year(self) -> bool:
        return self.start.year < self.end.year

    @property
    def is_ytd(self) -> bool:
        """1 January to a month end — what Setup's "YTD, ending <month>" asks for."""
        return (self.kind == KIND_RANGE and (self.start.month, self.start.day) == (1, 1)
                and self.end == month_end(self.end.year, self.end.month))

    def label(self, year: Optional[int] = None) -> str:
        """What a slide calls period ``year`` — "TTM Aug 2026", "YTD Aug 2026",
        "Jan 15 – Apr 14 2026"."""
        y = int(year if year is not None else self.year)
        if self.kind == KIND_R12M:
            return f"TTM {MONTH_ABBR[self.end.month]} {y}"
        if self.is_ytd:
            return f"YTD {MONTH_ABBR[self.end.month]} {y}"
        if self.kind == KIND_RANGE:
            shift = self.year - y
            start, end = _years_back(self.start, shift), _years_back(self.end, shift)
            return f"{_short(start)} – {_short(end)} {end.year}"
        return str(y)

    def describe(self) -> str:
        """One line for logs and tooltips."""
        return f"{self.kind} {self.start.isoformat()}..{self.end.isoformat()}"


def _short(day: date) -> str:
    return f"{MONTH_ABBR[day.month]} {day.day}"


def _years_back(day: date, years: int) -> date:
    """``day`` moved ``years`` years earlier; 29 Feb lands on 28 Feb in a common year."""
    target = day.year - years
    last = calendar.monthrange(target, day.month)[1]
    return date(target, day.month, min(day.day, last))


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def r12m_window(year: int, month: int) -> PeriodWindow:
    """The twelve months ending with ``month`` of ``year``."""
    start = date(year, 1, 1) if month == 12 else date(year - 1, month + 1, 1)
    return PeriodWindow(start=start, end=month_end(year, month), kind=KIND_R12M)


def window_for(choice: PeriodChoice, *, latest: Optional[Tuple[int, int]],
               year_pin: Optional[int] = None) -> Optional[PeriodWindow]:
    """The window a choice resolves to against the data, or ``None`` for the plain calendar.

    ``latest`` is ``(year, month)`` of the most recent billing in the book; ``year_pin`` the
    reporting year the author pinned (the max of a multi-select), if any.

    R12M ends in the anchor month: the author's "to" date when given, else the latest month
    in the data — in the pinned year when one is pinned, so "2025" means "TTM Aug 2025"
    against a book that runs to August 2026. A date range with no R12M is its own window.
    """
    if choice.basis == BASIS_R12M:
        if choice.date_to is not None:
            return r12m_window(choice.date_to.year, choice.date_to.month)
        if latest is None:
            return None
        year, month = latest
        if year_pin is not None and int(year_pin) < year:
            year = int(year_pin)
        return r12m_window(year, month)
    if choice.date_from is None and choice.date_to is None:
        return None
    start = choice.date_from or date(choice.date_to.year, 1, 1)
    end = choice.date_to or (month_end(*latest) if latest else date(start.year, 12, 31))
    if start > end:
        start, end = end, start
    too_long = _years_back(end, 1) >= start          # longer than one year: cannot repeat
    return PeriodWindow(start=start, end=end, kind=KIND_RESTRICT if too_long else KIND_RANGE)


def describe(choice: PeriodChoice, *, latest: Optional[Tuple[int, int]],
             year_pin: Optional[int] = None) -> str:
    """The period a Setup selection will report, as one sentence for the form.

    ``latest`` may be unknown (the warm-up has not read the book yet); the sentence then
    names the rule instead of the month rather than guessing one.
    """
    window = window_for(choice, latest=latest, year_pin=year_pin)
    if window is None:
        if choice.basis == BASIS_R12M:
            return ("R12M to the latest month in the data, against the 12 months before.")
        year = year_pin or (latest[0] if latest else None)
        return (f"YTD {year} against {year - 1}." if year
                else "YTD — the latest year in the data.")
    if window.kind == KIND_R12M:
        # Setup names the basis R12M; the slides keep the "TTM <month>" caption the
        # templates were written with (:meth:`PeriodWindow.label`).
        month = MONTH_ABBR[window.end.month]
        return (f"R12M {month} {window.year} ({_long(window.start)} – {_long(window.end)}) "
                f"against R12M {month} {window.year - 1}. Every figure uses these twelve "
                f"months.")
    if window.is_ytd:
        return (f"{window.label()} ({_long(window.start)} – {_long(window.end)}) against "
                f"{window.label(window.year - 1)}, the same months a year earlier.")
    if window.kind == KIND_RANGE:
        return (f"{_long(window.start)} – {_long(window.end)} against the same dates a year "
                f"earlier. Year filters follow the window.")
    return (f"Only billings from {_long(window.start)} to {_long(window.end)} count; years are "
            f"compared as calendar years inside that range.")


def _long(day: date) -> str:
    return f"{day.day} {MONTH_ABBR[day.month]} {day.year}"


def display_period(window: Optional[PeriodWindow], year: Any, *, prior: bool = False) -> str:
    """How a page names period ``year`` (or the one before it): "TTM Aug 2026", else "FY2026".

    ``year`` may be missing — a run that pinned none — in which case a relabelled window
    still names itself and the calendar basis says "current period" / "prior period".
    """
    y = int(year) if str(year or "").strip().isdigit() else None
    if window is not None and window.relabels:
        base = y if y is not None else window.year
        return window.label(base - 1 if prior else base)
    if y is None:
        return "prior period" if prior else "current period"
    return f"FY{y - 1}" if prior else f"FY{y}"


def year_pin(years: Any) -> Optional[int]:
    """The reporting year a Year filter pins — the max of a multi-select, else ``None``."""
    values = years if isinstance(years, (list, tuple, set)) else (years,)
    pinned = [int(y) for y in values if str(y).strip().isdigit()]
    return max(pinned) if pinned else None


# ── the SQL the working book is built with ───────────────────────────────────

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")


def month_from_name_sql(column: str) -> str:
    """``Month_Name`` → 1..12 ("January" and "Jan" alike), NULL for anything else."""
    cases = " ".join(f"WHEN '{m}' THEN {i}" for i, m in enumerate(_MONTHS, start=1))
    return f"(CASE substr(lower(trim(\"{column}\")), 1, 3) {cases} END)"


@dataclass(frozen=True)
class DateParts:
    """How to read a row's month and ``MM-DD`` in SQL — from an ISO date, else a month name."""

    month: str
    month_day: str


def date_parts_sql(*, date_column: Optional[str], iso: bool,
                   month_name_column: Optional[str]) -> Optional[DateParts]:
    """The row's month and month-day, read the most precise way the book allows.

    An ISO billing date gives the day; a month name alone gives the month, and every row is
    placed mid-month (``MM-15``), which is exact for any window that starts on the 1st and
    ends on a month end — every R12M window, and every range picked by month.
    """
    if date_column and iso:
        return DateParts(month=f'CAST(substr("{date_column}", 6, 2) AS INTEGER)',
                         month_day=f'substr("{date_column}", 6, 5)')
    if month_name_column:
        month = month_from_name_sql(month_name_column)
        return DateParts(month=month, month_day=f"printf('%02d-15', {month})")
    return None


def period_year_sql(window: PeriodWindow, parts: DateParts, year_column: str) -> str:
    """The period year a row belongs to under ``window`` — NULL for a row outside every one.

    The window repeats yearly, so only its month-day bounds matter per row: a window that
    crosses New Year (Sep–Aug) labels its autumn rows with the NEXT year.
    """
    md, lo, hi = parts.month_day, window.start.strftime("%m-%d"), window.end.strftime("%m-%d")
    year = f'CAST("{year_column}" AS INTEGER)'
    if window.crosses_year:
        return (f"(CASE WHEN {md} >= '{lo}' THEN {year} + 1 "
                f"WHEN {md} <= '{hi}' THEN {year} END)")
    return f"(CASE WHEN {md} BETWEEN '{lo}' AND '{hi}' THEN {year} END)"


def quarter_sql(month_sql: str) -> str:
    """``'Q1'``..``'Q4'`` from a 1..12 month expression.

    Fully parenthesised: SQLite binds ``||`` TIGHTER than ``/``, so ``'Q' || (m + 2) / 3``
    is ``('Q' || (m + 2)) / 3`` — a number, not a label.
    """
    return f"('Q' || ((({month_sql}) + 2) / 3))"


def is_iso_date(values: Sequence[Any]) -> bool:
    """Whether sampled billing dates read as ISO ``YYYY-MM-DD`` (a datetime suffix is fine)."""
    seen = [str(v).strip() for v in values if v not in (None, "")]
    return bool(seen) and all(len(v) >= 10 and v[4] == "-" and v[7] == "-"
                              and v[:4].isdigit() and v[5:7].isdigit() for v in seen)
