"""Years written INTO a template's wording, and how they follow the selection.

Templates are authored for one example period: "FY 2025", "Marsh GWP 2025", "2025 Rank",
"2025 Reflections", "Opportunities for 2026", a cover dated "22 July 2026". A deck built for
another period has to say that period everywhere — titles, table headers, panel headings —
not only in the slots the engine fills.

Three kinds of year, three rules:

* a **reporting** year ("FY 2025", "SoW% 2025") moves with the reporting year: the template's
  own reporting year (:func:`template_year`) maps onto the selected one, and the year before
  it onto the year before (or onto the period labels — "TTM Aug 2026" — on an R12M/YTD run);
* a **forward** year ("Opportunities for 2026") names the year being planned for: the year
  after a complete reporting year, the reporting year itself while it is still running;
* a **date** ("22 July 2026") is when the deck is presented: the day it is built.

The template year used to be read from text boxes only, so a template whose years all sit
in table cells (the portfolio pages' "Marsh GWP 2025" headers) had none, and every one of
its pages kept saying 2025 whatever was selected.

Pure: text in, patterns and counts out.
"""
from __future__ import annotations

import calendar
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, List, Mapping, Optional, Tuple

_MONTHS = "|".join(calendar.month_name[1:] + calendar.month_abbr[1:])

# "22 July 2026", "22 Jul 2026", "July 22, 2026" — a presentation date, not a period.
DATE = re.compile(rf"\b(?:\d{{1,2}}\s+(?:{_MONTHS})\.?,?\s+|(?:{_MONTHS})\.?\s+\d{{1,2}},?\s+)"
                  rf"20\d{{2}}\b")
# "Opportunities for 2026", "Priorities for 2026" — the year being planned for.
FORWARD = re.compile(r"\bfor\s+(20\d{2})\b", re.I)
YEAR = re.compile(r"\b(20\d{2})\b")

Sub = Tuple[Any, Any]


COPYRIGHT = re.compile(r"(?:©|\(c\)|copyright)\s*20\d{2}\b", re.I)


def _period_years(text: str) -> List[int]:
    """The years in ``text`` that name a reporting period (dates, copyright lines and
    forward years removed)."""
    text = FORWARD.sub(" ", COPYRIGHT.sub(" ", DATE.sub(" ", text or "")))
    return [int(y) for y in YEAR.findall(text)]


def template_year(texts: Iterable[str]) -> Optional[int]:
    """The template's authored reporting year: the most frequent period year in its text,
    the later one on a tie ("TTM April 2026" beside "TTM April 2025" reports on 2026)."""
    counts: Counter = Counter()
    for text in texts:
        counts.update(_period_years(text))
    if not counts:
        return None
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def shape_texts(template) -> Iterable[str]:
    """Every piece of authored wording in an analysed template — text boxes AND table cells."""
    for slide in template.slides:
        for shape in slide.shapes:
            if shape.text:
                yield shape.text
            for row in shape.table or ():
                for cell in row:
                    if cell:
                        yield str(cell)


def format_date(day: date) -> str:
    """How a cover dates a deck: "28 September 2026"."""
    return f"{day.day} {calendar.month_name[day.month]} {day.year}"


def forward_year(reporting_year: int, latest: Optional[Tuple[int, int]]) -> int:
    """The year a deck plans for: next year once the reporting year is complete, else the
    reporting year itself (a deck on YTD Aug 2026 plans for the rest of 2026)."""
    if latest and int(latest[0]) == int(reporting_year) and int(latest[1]) < 12:
        return int(reporting_year)
    return int(reporting_year) + 1


# ONE pass over the text, so a year written by one rule is never moved again by another
# (a cover dated today, or "for 2025", must not then be shifted as a reporting year).
_ANY_YEAR = re.compile(
    rf"(?P<date>{DATE.pattern})"
    r"|(?P<copy>(?:©|\(c\)|copyright)\s*)(?P<cyear>20\d{2})\b"
    r"|(?P<fwd>\bfor\s+)(?P<fyear>20\d{2})\b"
    r"|(?P<fy>\bFY\s*)?\b(?P<year>20\d{2})\b",
    re.I,
)


@dataclass(frozen=True)
class YearRule:
    """How each kind of year in a template is rewritten for one deck."""

    deck_date: str                        # the cover date
    this_year: int = 0                    # a copyright line's year: when the deck is built
    delta: int = 0                        # selected reporting year − template year
    forward: Optional[int] = None         # the year planned for, on a calendar deck
    labels: Mapping[str, str] = field(default_factory=dict)   # year → period label
    reporting_year: Optional[int] = None

    def __call__(self, m) -> str:
        if m.group("date"):
            return self.deck_date
        if m.group("cyear"):
            return m.group("copy") + str(self.this_year or m.group("cyear"))
        if m.group("fyear"):
            return m.group("fwd") + self._forward(int(m.group("fyear")))
        year = str(int(m.group("year")) + self.delta)
        if year in self.labels:
            return self.labels[year]
        return (m.group("fy") or "") + year

    def _forward(self, authored: int) -> str:
        if self.labels:
            # A rolling or part-year deck plans for the next twelve months, not a year.
            moved = authored + self.delta
            if self.reporting_year is not None and moved >= self.reporting_year:
                return "the next twelve months"
            return self.labels.get(str(moved), str(moved))
        return str(self.forward if self.forward else authored + self.delta)


def year_subs(values: Mapping[str, Any], *, today: Optional[date] = None) -> List[Sub]:
    """The label substitution that makes a template's years follow the selection.

    Without a template or reporting year only dates and copyright lines move; every other
    year is left as the author wrote it.
    """
    built = _as_date(values.get("deck_date")) or today or date.today()
    ty, py = values.get("template_year"), values.get("period_year")
    if not (ty and py):
        return [(_ANY_YEAR, YearRule(deck_date=format_date(built), this_year=built.year))]
    labels = {str(k): str(v) for k, v in (values.get("period_labels") or {}).items()}
    forward = values.get("forward_year")
    rule = YearRule(deck_date=format_date(built), this_year=built.year,
                    delta=int(py) - int(ty), forward=int(forward) if forward else None,
                    labels=labels, reporting_year=int(py))
    return [(_ANY_YEAR, rule)]


# Only the authored "YTD" moves: a caption the author wrote as TTM (the country page's
# rolling table) is TTM on every basis, and its header is written by its own slot.
_BASIS_WORD = re.compile(r"\bYTD\b")


def basis_subs(values: Mapping[str, Any]) -> List[Sub]:
    """"YTD Performance" names the deck's basis: on a rolling deck it reads "TTM Performance".

    Only the basis words a period label starts with ("TTM Aug 2026", "YTD Aug 2026") are
    used; a date-range label has no single word for its basis, so the heading is left.
    """
    labels = [str(v) for v in (values.get("period_labels") or {}).values()]
    word = labels[0].split()[0] if labels and labels[0].split() else ""
    return [(_BASIS_WORD, word)] if word in ("TTM", "YTD") else []


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None
