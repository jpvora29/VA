"""Who is speaking, and when — the attribution line above each turn.

A transcript with no attribution reads as one continuous voice, which is exactly
wrong for an app whose whole claim is that the numbers came from somewhere. So
every turn is stamped: the analyst's turns say who answered, on what data, and at
what time; the reader's turns say the same for their side.

The stamp is recorded at commit time (``ui.callbacks``) and only ever *read* here
— a transcript saved before stamping existed simply renders without a time rather
than being labelled with the time it was re-opened.

Pure presentation: strings in, components out.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from dash import html

#: What the analyst's turns are attributed to.
ANALYST_NAME = "Virtual Analyst"


def now_stamp() -> str:
    """The stamp to record on a turn as it is committed."""
    return datetime.now().isoformat(timespec="seconds")


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts
    text = str(ts or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def format_stamp(ts: Any) -> str:
    """"9 Sep 2026, 4:14 PM" — written out rather than left as an ISO string.

    Built by hand instead of with ``strftime``: the no-pad directives that would
    give "9" and "4" (``%-d``, ``%-I``) are POSIX-only, and this app runs on
    Windows too.
    """
    moment = _parse(ts)
    if moment is None:
        return ""
    hour = moment.hour % 12 or 12
    meridiem = "AM" if moment.hour < 12 else "PM"
    return (
        f"{moment.day} {moment.strftime('%b')} {moment.year}, "
        f"{hour}:{moment.minute:02d} {meridiem}"
    )


def initial_of(name: str) -> str:
    """The one letter an avatar carries."""
    return (str(name or "").strip()[:1] or "?").upper()


def assistant_header(*, source: str = "", ts: Any = ""):
    """Mark, name, what the answer was drawn from, and when it was written.

    ``source`` is the dataset the turn actually read (stated again, in more
    detail, on the answer's own provenance line). It is omitted rather than
    guessed at when the turn recorded none.
    """
    stamp = format_stamp(ts)
    return html.Div(
        [
            html.Div("VA", className="turn-avatar turn-avatar-va"),
            html.Span(ANALYST_NAME, className="turn-name"),
            html.Span(source, className="turn-source") if source else None,
            html.Span(stamp, className="turn-stamp") if stamp else None,
        ],
        className="turn-header",
    )


def user_footer(*, initial: str = "", ts: Any = ""):
    """The reader's side: their mark and the time they asked.

    Under the bubble rather than above it, because the question is the thing to
    read and the attribution is the thing to check.
    """
    stamp = format_stamp(ts)
    if not stamp and not initial:
        return None
    return html.Div(
        [
            html.Span(stamp, className="turn-stamp") if stamp else None,
            html.Div(initial_of(initial), className="turn-avatar turn-avatar-you")
            if initial
            else None,
        ],
        className="turn-footer",
    )
