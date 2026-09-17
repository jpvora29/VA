"""Drop an answer the user has already moved past.

The Setup form deliberately stays LIVE while it is working. The busy overlay is a progress
cue, not a control — ``pointer-events: none`` in ``assets/studio_authoring.css``, with the
comment that says why: *a change made while it is up must still land*.

That promise needs keeping, and concurrency is what breaks it. Four callbacks answer a filter
change (the option cascade, the scope preview, the survey panel, the survey peers), the browser
runs them at the same time, and each takes anything from 20 ms with a warm cube to minutes with
a cold one. So two changes in quick succession put two sets of answers in flight — and nothing
said the second one wins. HTTP responses can arrive in either order, and the loser quietly
repainted the form for a selection the user had already left: dropdowns narrowed to the
previous carrier, a preview showing the previous scope's total.

What is kept here is ONE fact per viewer: the selection their newest callback started on. A
callback takes a :class:`Ticket` when it begins and checks it before it returns; an answer for
a superseded selection is dropped, and the newer answer — already in flight — lands instead.

Not a lock and not a queue: the work still runs concurrently. It just cannot overwrite a fresher
answer with a staler one.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Mapping

from logger import get_logger

logger = get_logger(__name__)

# One entry per browser session, so this is small. Bounded anyway: a process that has served
# thousands of sessions should not carry a fact about every one of them for ever.
_MAX_VIEWERS = 512

_latest: Dict[str, str] = {}
_guard = threading.Lock()


@dataclass(frozen=True)
class Ticket:
    """Proof of which viewer asked, and which selection they asked about."""

    viewer: str
    selection: str


def viewer_key() -> str:
    """Who is asking — per browser session, so one user's typing never drops another's answer.

    The Flask session cookie is the natural key: it is per browser, it already exists (the
    sign-in flow sets it), and it needs nothing added to the callback's signature. Outside a
    request, or with no cookie yet, everyone shares one key — for a single-user desktop run
    that is exactly right, and the cost if it is ever wrong is one dropped repaint that the
    next change corrects, never a wrong answer.
    """
    try:
        from flask import request

        return request.cookies.get("session") or request.remote_addr or "local"
    except Exception:  # noqa: BLE001 — called outside a request (tests, first render)
        return "local"


def selection_key(selection: Mapping[str, Any] | None) -> str:
    """A stable string for a selection, whatever order the controls were read in."""
    return repr(sorted((str(field), repr(value))
                       for field, value in (selection or {}).items()))


def begin(selection: Mapping[str, Any] | None) -> Ticket:
    """Record ``selection`` as the newest one this viewer is waiting on."""
    ticket = Ticket(viewer=viewer_key(), selection=selection_key(selection))
    with _guard:
        if len(_latest) >= _MAX_VIEWERS and ticket.viewer not in _latest:
            _latest.clear()
        _latest[ticket.viewer] = ticket.selection
    return ticket


def superseded(ticket: Ticket) -> bool:
    """Whether the viewer has since moved to a different selection.

    False when nothing newer has begun — including the case where nothing was recorded at
    all, so a caller that never called :func:`begin` is never told its answer is stale.
    """
    with _guard:
        current = _latest.get(ticket.viewer, ticket.selection)
    return current != ticket.selection


def stale(ticket: Ticket, what: str) -> bool:
    """:func:`superseded`, with a line in the log naming what was dropped."""
    if not superseded(ticket):
        return False
    logger.info("setup: dropped a stale %s — the filters moved on while it was computing",
                what)
    return True


def clear() -> None:
    """Forget every viewer's latest selection (tests)."""
    with _guard:
        _latest.clear()
