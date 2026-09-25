"""When a decision is due, said in words — the arithmetic behind the review agenda.

A date chip is not urgency. "8 Sep" beside a decision tells the reader nothing
unless they also know today's date and are willing to do the subtraction; the
board's own review notes recorded that the one overdue record on the sample
board wore the same ordinary chip as every other. So every due date is turned
into a *state* with a sentence — "1 day overdue", "Due today", "in 3 days" — and
the agenda groups the queue by that state rather than by status.

Everything here is pure: plain decision dicts and a ``today`` in, dataclasses
out. ``today`` is always passed rather than read from the clock, so the grouping
is testable and the whole board renders against one consistent date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Optional, Sequence

# Tones drive the CSS suffix and nothing else; the label carries the meaning.
OVERDUE = "overdue"
TODAY = "today"
SOON = "soon"
LATER = "later"
NONE = "none"

#: Past this many days away a due date is just a date — spelling out "in 23 days"
#: adds a number the reader has to parse without making anything more urgent.
_SOON_DAYS = 7


@dataclass(frozen=True)
class DueState:
    """A due date as the reader needs it: the date, and what it means today."""

    tone: str
    label: str
    date_text: str
    days: Optional[int] = None  # signed; negative is overdue, None when undated

    @property
    def is_overdue(self) -> bool:
        return self.tone == OVERDUE


@dataclass(frozen=True)
class AgendaGroup:
    """One band of the agenda — a heading, and the decisions under it."""

    key: str
    label: str
    tone: str
    items: tuple[dict[str, Any], ...]

    @property
    def count(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class Day:
    """One cell of the week ribbon."""

    day: date
    weekday: str
    number: int
    is_today: bool
    due_count: int


@dataclass(frozen=True)
class Week:
    """The week the agenda is centred on, and how it relates to today."""

    start: date
    end: date
    offset: int
    days: tuple[Day, ...]
    label: str

    @property
    def is_current(self) -> bool:
        return self.offset == 0


# ── Parsing ─────────────────────────────────────────────────────────────────


def parse_date(value: Any) -> Optional[date]:
    """An ISO ``YYYY-MM-DD`` string as a date, or ``None`` when it is not one.

    Dates arrive from an ``<input type="date">`` and from hand-edited rows, so a
    blank or a malformed value has to be an ordinary "no due date" rather than an
    exception thrown while painting the board.
    """
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def due_of(decision: dict[str, Any]) -> Optional[date]:
    return parse_date(decision.get("due_date"))


# ── Due state ───────────────────────────────────────────────────────────────


def format_day(value: date) -> str:
    """"8 Sep" — the short form the agenda's date column prints."""
    return f"{value.day} {value.strftime('%b')}"


def format_span(start: date, end: date) -> str:
    """"7–13 Sep 2026", collapsing the month and year when they are shared."""
    if start.year != end.year:
        return f"{format_day(start)} {start.year} – {format_day(end)} {end.year}"
    if start.month != end.month:
        return f"{format_day(start)} – {format_day(end)} {end.year}"
    return f"{start.day}–{end.day} {end.strftime('%b')} {end.year}"


def due_state(value: Any, today: date) -> DueState:
    """What this due date means today, as a tone and a sentence."""
    when = parse_date(value)
    if when is None:
        return DueState(tone=NONE, label="No due date", date_text="—")
    days = (when - today).days
    return DueState(
        tone=_tone(days),
        label=_due_label(days),
        date_text=format_day(when),
        days=days,
    )


def _tone(days: int) -> str:
    if days < 0:
        return OVERDUE
    if days == 0:
        return TODAY
    return SOON if days <= _SOON_DAYS else LATER


def _due_label(days: int) -> str:
    if days < 0:
        return _plural(-days, "day") + " overdue"
    if days == 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    if days <= _SOON_DAYS:
        return f"in {_plural(days, 'day')}"
    return ""


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


# ── The week ribbon ─────────────────────────────────────────────────────────


def week_start(day: date) -> date:
    """The Monday of the week containing ``day``."""
    return day - timedelta(days=day.weekday())


def week_for(
    today: date, offset: int, decisions: Sequence[dict[str, Any]] = ()
) -> Week:
    """The week ``offset`` weeks from today's, with a due-count per day.

    The counts are what make the ribbon worth its space: a dot under Tuesday says
    something is due then before the reader has scrolled to the row.
    """
    start = week_start(today) + timedelta(weeks=offset)
    due_counts = _due_counts(decisions)
    days = tuple(
        Day(
            day=start + timedelta(days=i),
            weekday=(start + timedelta(days=i)).strftime("%a"),
            number=(start + timedelta(days=i)).day,
            is_today=(start + timedelta(days=i)) == today,
            due_count=due_counts.get(start + timedelta(days=i), 0),
        )
        for i in range(7)
    )
    end = start + timedelta(days=6)
    return Week(
        start=start,
        end=end,
        offset=offset,
        days=days,
        label=f"{week_name(offset)} · {format_span(start, end)}",
    )


def week_name(offset: int) -> str:
    """"This week" / "Next week" / "Last week" / "In 3 weeks"."""
    names = {0: "This week", 1: "Next week", -1: "Last week"}
    if offset in names:
        return names[offset]
    return f"In {_plural(offset, 'week')}" if offset > 0 else f"{_plural(-offset, 'week')} ago"


def _due_counts(decisions: Iterable[dict[str, Any]]) -> dict[date, int]:
    counts: dict[date, int] = {}
    for d in decisions:
        when = due_of(d)
        if when is not None:
            counts[when] = counts.get(when, 0) + 1
    return counts


# ── Grouping ────────────────────────────────────────────────────────────────


def agenda_groups(
    decisions: Sequence[dict[str, Any]], today: date, week: Week
) -> list[AgendaGroup]:
    """The queue banded into overdue, the shown week, the one after, and the rest.

    Overdue is measured against *today*, not against the shown week: a decision
    whose date has passed is late whichever week the reader happens to be
    browsing, and paging the ribbon must never make a late decision disappear.
    The two named week bands slide with the ribbon, so their headings are named
    from the week's own offset.
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        OVERDUE: [], "week": [], "next": [], LATER: [], NONE: [],
    }
    next_start = week.end + timedelta(days=1)
    next_end = next_start + timedelta(days=6)
    for d in decisions:
        buckets[_bucket(due_of(d), today, week, next_start, next_end)].append(d)

    bands = (
        (OVERDUE, "Overdue", OVERDUE),
        ("week", week_name(week.offset), TODAY if week.is_current else LATER),
        ("next", week_name(week.offset + 1), SOON),
        (LATER, "Later", LATER),
        (NONE, "No due date", NONE),
    )
    return [
        AgendaGroup(key=key, label=label, tone=tone, items=tuple(buckets[key]))
        for key, label, tone in bands
        if buckets[key]
    ]


def _bucket(
    when: Optional[date], today: date, week: Week, next_start: date, next_end: date
) -> str:
    if when is None:
        return NONE
    if when < today:
        return OVERDUE
    if week.start <= when <= week.end:
        return "week"
    if next_start <= when <= next_end:
        return "next"
    return LATER


def overdue_count(decisions: Iterable[dict[str, Any]], today: date) -> int:
    """How many of these decisions are past their due date."""
    return sum(1 for d in decisions if (due_of(d) or today) < today)


def sort_by_due(decisions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Soonest first, undated last — the order the agenda reads rows in.

    Applied inside a band as well as across the queue, because a band holding
    four decisions still owes the reader the nearest deadline at the top.
    """
    return sorted(
        decisions,
        key=lambda d: (not d.get("pinned"), due_of(d) or date.max, d["title"].lower()),
    )
