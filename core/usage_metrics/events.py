"""What a usage row says: who did it, in which tab, and what they did.

Everything here is pure — building a row never touches a file, a session or the
database — so the shape of the workbook is testable on its own. ``recorder`` decides
when a row is written and ``workbook`` how.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ANONYMOUS = "anonymous"

# Workbook columns, in order. ``UsageEvent.as_row`` fills them.
COLUMNS: tuple[str, ...] = (
    "Timestamp",
    "User ID",
    "Email",
    "Username",
    "Tab",
    "Action",
    "Studio selections",
    "Question",
    "Reply",
    "Uploaded files",
    "Status",
    "Notes",
)

# Selection keys that are plumbing, not choices the user made on the Setup form.
_STUDIO_INTERNAL_KEYS = frozenset(
    {
        "ai",
        "ai_story",
        "breakdowns",
        "dataset_rev",
        "meeting_length",
        "slides",
        "template_path",
    }
)


@dataclass(frozen=True)
class UsageActor:
    """The signed-in person a row belongs to."""

    user_id: str
    username: str
    email: str

    @property
    def file_key(self) -> str:
        """What names this person's workbook: their email, else username, else id."""
        return self.email or self.username or self.user_id or ANONYMOUS


@dataclass(frozen=True)
class UsageEvent:
    """One thing a user did, before it is stamped with who and when."""

    tab: str
    action: str
    studio_selections: str = ""
    question: str = ""
    reply: str = ""
    uploaded_files: str = ""
    status: str = "ok"
    notes: str = ""
    at: datetime = field(default_factory=datetime.now)

    def as_row(self, actor: UsageActor) -> list[Any]:
        """The workbook row, in ``COLUMNS`` order."""
        return [
            self.at.replace(microsecond=0),
            actor.user_id,
            actor.email,
            actor.username,
            self.tab,
            self.action,
            self.studio_selections,
            self.question,
            self.reply,
            self.uploaded_files,
            self.status,
            self.notes,
        ]


# ── actors ────────────────────────────────────────────────────────────────────


def make_actor(user_id: Any, username: Any) -> UsageActor:
    """An actor from a user id and username; the email is the username when it is one.

    Under SSO the account key — the username — is the email address
    (``core.store.users.get_or_create_sso_user``); a local sign-in has none.
    """
    name = str(username or "").strip()
    uid = "" if user_id is None else str(user_id).strip()
    email = name.lower() if "@" in name else ""
    if not uid and not name:
        return UsageActor(user_id="", username=ANONYMOUS, email="")
    return UsageActor(user_id=uid, username=name, email=email)


def actor_from_store(user_store: Mapping[str, Any] | None) -> UsageActor | None:
    """The actor in the browser ``user-store``, or ``None`` when nobody is signed in."""
    if not user_store or user_store.get("id") is None:
        return None
    return make_actor(user_store.get("id"), user_store.get("username"))


# ── events ────────────────────────────────────────────────────────────────────


def tab_visit_event(tab_label: str) -> UsageEvent:
    """The user opened a workspace tab."""
    return UsageEvent(tab=tab_label, action="Opened tab")


def studio_generate_event(selection: Mapping[str, Any]) -> UsageEvent:
    """The user pressed Generate on Studio Setup with these selections."""
    return UsageEvent(
        tab="Studio",
        action="Generate deck",
        studio_selections=format_studio_selection(selection),
    )


def chat_turn_event(
    question: str,
    reply: str,
    *,
    status: str = "ok",
    thread_id: str = "",
    route: str = "",
) -> UsageEvent:
    """One Ask ICG question and the reply it got."""
    notes = "; ".join(
        part
        for part in (
            f"conversation {thread_id}" if thread_id else "",
            f"route {route}" if route else "",
        )
        if part
    )
    return UsageEvent(
        tab="Ask ICG",
        action="Asked question",
        question=question,
        reply=reply,
        status=status,
        notes=notes,
    )


def last_question_and_reply(messages: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    """The latest question in a chat transcript and the reply that follows it.

    The reply is empty when nothing answered the question yet (an error, or a turn
    that stopped to ask for clarification), never an older turn's answer.
    """
    reply = ""
    for message in reversed(messages):
        kind = message.get("type")
        if kind == "AIMessage" and not reply:
            reply = _content_text(message.get("content"))
        elif kind == "HumanMessage":
            return _content_text(message.get("content")), reply
    return "", ""


def upload_event(tab_label: str, filenames: Iterable[str], action: str) -> UsageEvent:
    """Files the user uploaded (Recap decks, MoM note and deck)."""
    names = [name for name in filenames if name]
    return UsageEvent(tab=tab_label, action=action, uploaded_files="\n".join(names))


# ── formatting ────────────────────────────────────────────────────────────────


def format_studio_selection(selection: Mapping[str, Any]) -> str:
    """One readable line per Setup choice, skipping plumbing keys and empty values."""
    lines = []
    for key, value in selection.items():
        if key in _STUDIO_INTERNAL_KEYS or _is_empty(value):
            continue
        lines.append(f"{_label(key)}: {format_value(value)}")
    return "\n".join(lines)


def format_value(value: Any) -> str:
    """A selection value as text: lists comma-joined, mappings as ``key=value; …``."""
    if isinstance(value, Mapping):
        return "; ".join(
            f"{key}={format_value(item)}"
            for key, item in value.items()
            if not _is_empty(item)
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(format_value(item) for item in value if not _is_empty(item))
    return str(value)


def _content_text(content: Any) -> str:
    """Message content as text — a list of content parts keeps only their text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") if isinstance(part, Mapping) else str(part)
            for part in content
        )
    return "" if content is None else str(content)


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _is_empty(value: Any) -> bool:
    return (
        value is None or value == "" or (hasattr(value, "__len__") and len(value) == 0)
    )
