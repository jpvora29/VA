"""The chat list's shape: which group each conversation sits in, and its time line.

Pure functions over the rows ``core.store.conversations.list_conversations``
returns, so the sidebar's reading order is testable without Dash or a database.

The rail reads top to bottom as a person scans their own history:

    PINNED                       the chats they chose to keep at hand
    CLIENTS                      then one group per client, "Zurich · Singapore",
                                 newest client first
    TODAY        OCT 6, 2026     then chats about no one client, by recency, with
                                 the date spelled out
    YESTERDAY    OCT 5, 2026     for the two groups people say by name
    PREVIOUS 7 DAYS
    SEPTEMBER 2026               and a month per group after that

Stored times are UTC (SQLite's ``CURRENT_TIMESTAMP``); everything here is in
the server's local time, which is the reader's in a local deployment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class ChatRow:
    """One conversation as the sidebar draws it."""

    id: str
    title: str
    pinned: bool
    when: Optional[datetime]  # local, naive; None when the stamp is unreadable
    #: "Zurich · Singapore", the answer's first sentence, and what the chat is
    #: waiting on (``core.store.chat_summary``). Empty for an unsummarised chat.
    client: str = ""
    preview: str = ""
    status: str = ""


@dataclass(frozen=True)
class ChatGroup:
    """A labelled run of rows: "Today · Oct 6, 2026"."""

    key: str
    label: str
    date_label: str
    rows: tuple[ChatRow, ...]
    #: "pinned", "client" or "recent": how the sidebar draws the group.
    kind: str = "recent"


def local_moment(updated_at: Any) -> Optional[datetime]:
    """A stored UTC stamp as naive local time, or None when it does not parse."""
    text = str(updated_at or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().replace(tzinfo=None)


def to_row(conversation: dict[str, Any]) -> ChatRow:
    """A ``list_conversations`` dict as a ``ChatRow``."""
    return ChatRow(
        id=str(conversation["id"]),
        title=str(conversation.get("title") or "New chat"),
        pinned=bool(conversation.get("pinned")),
        when=local_moment(conversation.get("updated_at")),
        client=str(conversation.get("client") or ""),
        preview=str(conversation.get("preview") or ""),
        status=str(conversation.get("status") or ""),
    )


def _long_date(day: datetime) -> str:
    """"Oct 6, 2026" — by hand, because %-d is POSIX-only."""
    return f"{day.strftime('%b')} {day.day}, {day.year}"


def _bucket(when: Optional[datetime], now: datetime) -> tuple[str, str, str]:
    """(key, label, date label) of the recency group a moment falls in."""
    if when is None:
        return "older", "Older", ""
    days = (now.date() - when.date()).days
    if days <= 0:
        return "today", "Today", _long_date(now)
    if days == 1:
        return "yesterday", "Yesterday", _long_date(when)
    if days < 7:
        return "week", "Previous 7 days", ""
    return f"month-{when:%Y-%m}", f"{when.strftime('%B')} {when.year}", ""


def group_conversations(
    conversations: Iterable[dict[str, Any]], now: datetime
) -> tuple[ChatGroup, ...]:
    """Pinned first, then one group per client, then recency groups.

    Each group keeps the input's order (newest first), so the clients are listed
    by their latest chat. A pinned chat is listed ONCE, under Pinned — two rows
    for one conversation would make the list look longer than the history it
    holds.
    """
    rows = [to_row(c) for c in conversations]
    groups: list[ChatGroup] = []
    pinned = tuple(r for r in rows if r.pinned)
    if pinned:
        groups.append(ChatGroup("pinned", "Pinned", "", pinned, kind="pinned"))
    unpinned = [r for r in rows if not r.pinned]
    groups.extend(client_groups(unpinned))
    groups.extend(recency_groups([r for r in unpinned if not r.client], now))
    return tuple(groups)


def client_slug(client: str) -> str:
    """A stable group key for a client name: "Zurich · Singapore" -> "zurich-singapore"."""
    return "-".join("".join(c if c.isalnum() else " " for c in client.lower()).split())


def client_groups(rows: Iterable[ChatRow]) -> list[ChatGroup]:
    """One group per client, in order of each client's newest chat."""
    members: dict[str, list[ChatRow]] = {}
    for row in rows:
        if row.client:
            members.setdefault(row.client, []).append(row)
    return [
        ChatGroup(f"client-{client_slug(name)}", name, "", tuple(group), kind="client")
        for name, group in members.items()
    ]


def recency_groups(rows: Iterable[ChatRow], now: datetime) -> list[ChatGroup]:
    """Today, Yesterday, Previous 7 days, then a month per group."""
    order: list[tuple[str, str, str]] = []
    members: dict[str, list[ChatRow]] = {}
    for row in rows:
        bucket = _bucket(row.when, now)
        if bucket[0] not in members:
            order.append(bucket)
            members[bucket[0]] = []
        members[bucket[0]].append(row)
    return [ChatGroup(key, label, date_label, tuple(members[key]))
            for key, label, date_label in order]


def clock_time(when: datetime) -> str:
    """"2:14 PM" — by hand, because %-I is POSIX-only."""
    hour = when.hour % 12 or 12
    return f"{hour}:{when:%M} {'AM' if when.hour < 12 else 'PM'}"


def relative_age(when: datetime, now: datetime) -> str:
    """"Just now", "5m ago", "21h ago", "3d ago", "2w ago" — or "" past a month."""
    seconds = max(0, int((now - when).total_seconds()))
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 7 * 86400:
        return f"{seconds // 86400}d ago"
    if seconds < 35 * 86400:
        return f"{seconds // (7 * 86400)}w ago"
    return ""


def row_meta(when: Optional[datetime], now: datetime) -> tuple[str, ...]:
    """The parts of a row's time line: "2:14 PM", "Just now".

    Within the last two days the clock time is what tells two chats apart; past
    that the group already says roughly when, so the row says which day.
    """
    if when is None:
        return ()
    days = (now.date() - when.date()).days
    first = clock_time(when) if days <= 1 else f"{when:%a} {when.day} {when:%b}"
    age = relative_age(when, now)
    return (first, age) if age else (first,)


#: The dot beside a row, by what the chat is waiting on.
WORKING_TONE = "working"
NEEDS_YOU_TONE = "needs-you"
FRESH_TONE = "fresh"
OLDER_TONE = "older"


def status_tone(row: ChatRow, now: datetime) -> str:
    """Blue while it works, amber when it needs an answer, green when answered
    in the last day, grey after that."""
    if row.status == "working":
        return WORKING_TONE
    if row.status == "needs_input":
        return NEEDS_YOU_TONE
    if row.when is not None and (now - row.when).total_seconds() < 86400:
        return FRESH_TONE
    return OLDER_TONE


def row_line(row: ChatRow) -> str:
    """The line under a row's title: what the chat is waiting on, else what it found.

    Empty when neither is known, and the row falls back to its time line.
    """
    if row.status == "working":
        return "Working…"
    if row.status == "needs_input":
        return "Needs your answer"
    return row.preview
