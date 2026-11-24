"""What the sidebar says about a conversation without opening it.

Three facts, read from the stored chat once, when it is saved:

    client   "Zurich · Singapore": the carrier and market of the latest answer,
             so the sidebar can group a user's chats by the client they are about
    preview  the latest answer's first sentence, so a row says what was found,
             not only what was asked
    status   working / needs_input / answered: what the chat is waiting on

Pure: a chat-store dict in, a :class:`ChatSummary` out. No I/O.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

WORKING = "working"
NEEDS_INPUT = "needs_input"
ANSWERED = "answered"

#: Longest preview a row prints before the ellipsis; the rail is 264px wide.
PREVIEW_CHARS = 90

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9$])")


@dataclass(frozen=True)
class ChatSummary:
    """The sidebar's view of one conversation."""

    client: str = ""
    preview: str = ""
    status: str = ""


def _readable(value: str) -> str:
    """ "ZURICH GROUP" -> "Zurich Group", "AIG" stays "AIG"; mixed case is kept.

    Words of three letters or fewer in an all-caps name are acronyms (AIG, AXA,
    QBE, HDI), so they keep their capitals.
    """
    text = str(value or "").strip()
    if not text.isupper():
        return text
    return " ".join(w if len(w) <= 3 else w.capitalize() for w in text.split())


def _chip_value(scope: Sequence[Mapping[str, Any]], key: str) -> str:
    for chip in scope or ():
        if isinstance(chip, Mapping) and chip.get("key") == key:
            return _readable(str(chip.get("value") or ""))
    return ""


def client_of(scope: Sequence[Mapping[str, Any]]) -> str:
    """ "Carrier · Country" from an answer's scope chips; "" with no carrier."""
    carrier = _chip_value(scope, "carrier")
    if not carrier:
        return ""
    country = _chip_value(scope, "country")
    return f"{carrier} · {country}" if country else carrier


def _plain(line: str) -> str:
    line = _HEADING.sub("", line)
    line = _BULLET.sub("", line)
    line = _LINK.sub(r"\1", line)
    return _EMPHASIS.sub("", line).strip()


def first_sentence(content: str, limit: int = PREVIEW_CHARS) -> str:
    """The first sentence of an answer's prose, without markdown, cut to ``limit``.

    A heading on its own is a label, not a finding, so the first line that is not
    a heading wins; a heading is used only when the answer has nothing else.
    """
    lines = [ln for ln in str(content or "").splitlines() if ln.strip()]
    prose = [ln for ln in lines if not _HEADING.match(ln)]
    first = _plain((prose or lines or [""])[0])
    sentence = _SENTENCE_END.split(first, maxsplit=1)[0].strip()
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1].rstrip(" ,;:") + "…"


def _last(messages: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any]:
    for message in reversed(messages):
        if message.get("type") == kind:
            return message
    return {}


def _status(chat: Mapping[str, Any], messages: Sequence[Mapping[str, Any]]) -> str:
    if chat.get("_running"):
        return WORKING
    last_turn = next(
        (
            m.get("type")
            for m in reversed(messages)
            if m.get("type") in ("AIMessage", "ClarifyCard", "Boardroom")
        ),
        "",
    )
    if last_turn == "ClarifyCard":
        return NEEDS_INPUT
    return ANSWERED if last_turn else ""


def summarize_chat(chat: Mapping[str, Any] | None) -> ChatSummary:
    """Client, preview and status for one stored chat."""
    chat = chat or {}
    messages = [m for m in chat.get("messages") or [] if isinstance(m, Mapping)]
    answer = _last(messages, "AIMessage")
    # A follow-up that names no carrier is still about the client the chat is
    # about, so the latest answer that DOES name one decides the group.
    clients = (
        client_of(m.get("scope") or [])
        for m in reversed(messages)
        if m.get("type") == "AIMessage"
    )
    return ChatSummary(
        client=next((c for c in clients if c), ""),
        preview=first_sentence(answer.get("content") or ""),
        status=_status(chat, messages),
    )
