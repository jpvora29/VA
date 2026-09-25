"""What the Decision Board shows for one set of controls.

The board's painter reads nine controls (view, archive scope, week, search,
four filters, sort) and writes nine regions (the queue, three parts of the week
ribbon and its visibility, the counts, the archive link, the owner options and
the view switch). Left in the callback that is one function doing nine jobs, and
every region has to re-derive the others' inputs.

So the controls are resolved once into a frozen :class:`BoardRequest`, and the
regions are built from it into a :class:`BoardView`. The callback in
``ui.decisions.callbacks`` then does nothing but unpack. Reading this module
tells you everything the board displays without opening a callback.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Sequence

from core.store import decisions as store
from ui.decisions import agenda as ag
from ui.decisions import model, queue, render


@dataclass(frozen=True)
class BoardRequest:
    """The controls, resolved. One place where a raw form value becomes a real one."""

    user_id: int
    today: date
    view: str = model.DEFAULT_VIEW
    scope: str = "active"
    week_offset: int = 0
    selected: Optional[str] = None
    search: str = ""
    statuses: tuple[str, ...] = ()
    priorities: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    sort: str = "due"

    @property
    def showing_archive(self) -> bool:
        return self.scope == "archived"


@dataclass(frozen=True)
class BoardView:
    """Everything the board paints, one field per region."""

    queue: Any
    week_label: str
    week_days: list[Any]
    at_this_week: bool
    ribbon_class: str
    counts: list[Any]
    archive: list[Any]
    owner_options: list[dict[str, str]]
    switch: Any


def build_board_request(
    *,
    user_id: int,
    view: Any,
    scope: Any,
    week_offset: Any,
    selected: Any,
    search: Any,
    statuses: Any,
    priorities: Any,
    owners: Any,
    sort: Any,
    today: Optional[date] = None,
) -> BoardRequest:
    """Turn the raw control values into a request nothing downstream re-reads.

    ``today`` is a parameter rather than a call to the clock inside the painter,
    so a test can fix the date and so every region of one repaint — the ribbon,
    the bands, the overdue count — agrees on which day it is.
    """
    return BoardRequest(
        user_id=user_id,
        today=today or date.today(),
        view=view if view in model.view_keys() else model.DEFAULT_VIEW,
        scope="archived" if scope == "archived" else "active",
        week_offset=_as_int(week_offset),
        selected=selected or None,
        search=(search or "").strip(),
        statuses=_as_tuple(statuses),
        priorities=_as_tuple(priorities),
        owners=_as_tuple(owners),
        sort=sort or "due",
    )


def build_board_view(request: BoardRequest) -> BoardView:
    """Read the records this request asks for, and paint every region from them."""
    decisions = _load(request)
    week = ag.week_for(request.today, request.week_offset, decisions)
    totals = store.count_by_scope(request.user_id)
    return BoardView(
        queue=_queue(request, decisions, week),
        week_label=week.label,
        week_days=queue.week_days(week),
        at_this_week=week.is_current,
        ribbon_class=render.ribbon_class(request.view),
        counts=render.counts_line(
            totals["active"], ag.overdue_count(_active(decisions), request.today)
        ),
        archive=render.archive_label(request.showing_archive, totals["archived"]),
        owner_options=model.owner_options(store.list_owners(request.user_id)),
        switch=render.view_switch(request.view),
    )


def _load(request: BoardRequest) -> list[dict[str, Any]]:
    return store.list_decisions(
        request.user_id,
        search=request.search or None,
        statuses=list(request.statuses) or None,
        priorities=list(request.priorities) or None,
        owners=list(request.owners) or None,
        scope=request.scope,
        sort=request.sort,
    )


def _queue(request: BoardRequest, decisions: list[dict[str, Any]], week: ag.Week) -> Any:
    """The left pane, in whichever of the three readings is selected."""
    if request.view == "board":
        return render.board_columns(
            decisions,
            request.today,
            request.selected,
            statuses=_columns_for(request.scope),
        )
    if request.view == "agenda":
        return queue.agenda_body(decisions, request.today, week, request.selected)
    return queue.list_body(decisions, request.today, request.selected)


def _columns_for(scope: str) -> tuple[str, ...]:
    """The archive is one column; the active queue is the other three."""
    return (store.ARCHIVED,) if scope == "archived" else store.ACTIVE_STATUSES


def _active(decisions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Overdue is only meaningful for records still in play."""
    return [d for d in decisions if d["status"] != store.ARCHIVED]


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)
