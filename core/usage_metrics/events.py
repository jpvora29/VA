"""What a usage row says, and which sheet of the user's workbook it goes on.

One sheet per workspace — Studio, Recap, MoM, Ask ICG — each with its own columns,
plus a Tab visits sheet. Every row starts with Timestamp, User ID and Email.

Everything here is pure — building a row never touches a file or the machine — so the
shape of the workbook is testable on its own. ``recorder`` decides when a row is
written and ``workbook`` how.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

STUDIO = "Studio"
RECAP = "Recap"
MOM = "MoM"
ASK_ICG = "Ask ICG"
TAB_VISITS = "Tab visits"

COMMON_COLUMNS: tuple[str, ...] = ("Timestamp", "User ID", "Email")

# Sheet name -> its columns after the common three. Order here is sheet order.
SHEET_COLUMNS: dict[str, tuple[str, ...]] = {
    STUDIO: (
        "Action",
        "Deliverable",
        "Filters",
        "Cuts",
        "Peers",
        "Peers by country",
        "Audience",
        "Style",
        "Data basis",
        "Period",
        "Survey carrier",
        "Survey peers",
        "Dataset",
        "Other selections",
    ),
    RECAP: ("Action", "Uploaded files", "File count"),
    MOM: ("Action", "Mode", "Note file", "Deck file"),
    ASK_ICG: ("Question", "Reply", "Status", "Conversation", "Route"),
    TAB_VISITS: ("Tab",),
}

# Studio selection key -> its column. Keys not listed (and not plumbing) land in
# "Other selections", so a new Setup control is never silently dropped.
_STUDIO_KEY_COLUMNS = {
    "report": "Deliverable",
    "filters": "Filters",
    "cuts": "Cuts",
    "peers": "Peers",
    "peers_by_country": "Peers by country",
    "audience": "Audience",
    "style": "Style",
    "data_basis": "Data basis",
    "survey_carrier": "Survey carrier",
    "survey_peers_by_country": "Survey peers",
    "dataset_id": "Dataset",
}
_STUDIO_PERIOD_KEYS = ("period_basis", "date_from", "date_to")
# Selection keys that are plumbing, not choices the user made on the Setup form.
_STUDIO_INTERNAL_KEYS = frozenset(
    {
        "ai",
        "ai_story",
        "breakdowns",
        "dataset_rev",
        "meeting_length",
        "slides",
        "survey_peers",  # the flat copy of survey_peers_by_country
        "template_path",
    }
)


@dataclass(frozen=True)
class UsageActor:
    """The person a row belongs to: their OS login and work email."""

    user_id: str
    email: str


@dataclass(frozen=True)
class UsageEvent:
    """One thing a user did: the sheet it belongs on and its column values."""

    sheet: str
    values: Mapping[str, Any]
    at: datetime = field(default_factory=datetime.now)

    def as_row(self, actor: UsageActor) -> list[Any]:
        """The row for ``sheet``, in ``sheet_columns(sheet)`` order."""
        specific = [self.values.get(name, "") for name in SHEET_COLUMNS[self.sheet]]
        return [self.at.replace(microsecond=0), actor.user_id, actor.email, *specific]


def sheet_columns(sheet: str) -> tuple[str, ...]:
    return (*COMMON_COLUMNS, *SHEET_COLUMNS[sheet])


# ── events ────────────────────────────────────────────────────────────────────


def tab_visit_event(tab_label: str) -> UsageEvent:
    """The user opened a workspace tab."""
    return UsageEvent(TAB_VISITS, {"Tab": tab_label})


def studio_generate_event(selection: Mapping[str, Any]) -> UsageEvent:
    """The user pressed Generate on Studio Setup with these selections."""
    return UsageEvent(STUDIO, {"Action": "Generate deck", **studio_columns(selection)})


def chat_turn_event(
    question: str,
    reply: str,
    *,
    status: str = "ok",
    thread_id: str = "",
    route: str = "",
) -> UsageEvent:
    """One Ask ICG question and the reply it got."""
    return UsageEvent(
        ASK_ICG,
        {
            "Question": question,
            "Reply": reply,
            "Status": status,
            "Conversation": thread_id,
            "Route": route,
        },
    )


def recap_upload_event(filenames: Iterable[str]) -> UsageEvent:
    """The QBR decks the user uploaded to Recap."""
    names = [name for name in filenames if name]
    return UsageEvent(
        RECAP,
        {
            "Action": "Uploaded QBR decks",
            "Uploaded files": "\n".join(names),
            "File count": len(names),
        },
    )


def mom_generate_event(mode_label: str, note_file: str, deck_file: str) -> UsageEvent:
    """The user started a MoM run on this note and deck."""
    return UsageEvent(
        MOM,
        {
            "Action": "Generate",
            "Mode": mode_label,
            "Note file": note_file,
            "Deck file": deck_file,
        },
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


# ── Studio selection -> columns ───────────────────────────────────────────────


def studio_columns(selection: Mapping[str, Any]) -> dict[str, str]:
    """The Studio sheet's selection columns for one Generate."""
    columns: dict[str, str] = {}
    other: list[str] = []
    for key, value in selection.items():
        if (
            key in _STUDIO_INTERNAL_KEYS
            or key in _STUDIO_PERIOD_KEYS
            or _is_empty(value)
        ):
            continue
        if key in _STUDIO_KEY_COLUMNS:
            columns[_STUDIO_KEY_COLUMNS[key]] = format_value(value)
        else:
            other.append(f"{_label(key)}: {format_value(value)}")
    columns["Period"] = format_period(selection)
    columns["Other selections"] = "\n".join(other)
    return columns


def format_period(selection: Mapping[str, Any]) -> str:
    """The reporting period: calendar unless Setup chose another basis or dates."""
    basis = str(selection.get("period_basis") or "calendar")
    start, end = selection.get("date_from"), selection.get("date_to")
    if start or end:
        return f"{basis}: {start or '…'} to {end or '…'}"
    return basis


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
