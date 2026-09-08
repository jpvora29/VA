"""Slash commands — the tasks this assistant is for, said in one word.

A blank prompt box asks the user to guess what the product can do, and most of
them guess low: they type a lookup, get a number, and never find out that the
same box will brief them, decompose a movement, or find whitespace. The commands
are that capability list, made typeable.

They are NOT a second assistant. A command expands into an ordinary question and
sets the answer SHAPE it implies (`core.agents.common.answer_shape`), then runs
the normal graph — so `/brief Zurich Canada` and "brief me on Zurich in Canada"
take exactly the same path and cannot drift apart.

Adding one is adding a row to `COMMANDS`; nothing else branches on the name.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

# A leading /word, and everything after it. Anything else is a normal question —
# a question that merely contains a slash ("premium w/ Zurich") is not a command.
_COMMAND = re.compile(r"^\s*/([a-z][a-z-]*)\s*(.*)$", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Command:
    """One task, and the question it becomes.

    `template` takes the rest of the line. `shape` is the answer shape the task
    implies — stated here rather than left to detection, because the user has
    just told us what they want and re-deriving it from prose could disagree.
    """

    name: str
    label: str
    icon: str
    hint: str
    template: str
    shape: str = ""
    needs_subject: bool = True

    def expand(self, rest: str) -> str:
        """The natural-language question this command stands for."""
        subject = (rest or "").strip()
        return self.template.format(subject=subject).strip()


COMMANDS: Tuple[Command, ...] = (
    Command(
        "brief",
        "/brief",
        "bi bi-file-earmark-text",
        "Five-minute summary of an account or market",
        "Brief me on {subject}: the three numbers that matter, what changed, and what to watch.",
        shape="briefing",
    ),
    Command(
        "compare",
        "/compare",
        "bi bi-layout-split",
        "Put two subjects side by side",
        "Compare {subject}. Lead with the verdict, then only where they actually differ.",
        shape="comparison",
    ),
    Command(
        "explain",
        "/explain",
        "bi bi-diagram-3",
        "Break a movement down into what caused it",
        "Explain the change in {subject}: which slices drove it, and by how much each.",
        shape="driver",
    ),
    Command(
        "whitespace",
        "/whitespace",
        "bi bi-grid-1x2",
        "Where the premium is that we do not write",
        "Where is the whitespace for {subject}? Rank it by unwritten premium in currency.",
        shape="advisory",
    ),
    Command(
        "trend",
        "/trend",
        "bi bi-graph-up-arrow",
        "How a measure has moved over time",
        "Show the trend for {subject}: the shape of the series and where it turned.",
        shape="trend",
    ),
    Command(
        "rank",
        "/rank",
        "bi bi-list-ol",
        "Order a set by a measure",
        "Rank {subject}. Give the ranked table and the one thing in it a reader would not expect.",
        shape="ranking",
    ),
)

BY_NAME = {command.name: command for command in COMMANDS}


def find(name: str) -> Optional[Command]:
    """The command for a bare name (no slash), or ``None``."""
    return BY_NAME.get((name or "").strip().lower().lstrip("/"))


def parse(text: str) -> Tuple[Optional[Command], str]:
    """``(command, rest)`` for a line that starts with one, else ``(None, text)``."""
    match = _COMMAND.match(text or "")
    if not match:
        return None, text or ""
    command = find(match.group(1))
    if command is None:
        return None, text or ""
    return command, match.group(2).strip()


def expand(text: str) -> Tuple[str, str]:
    """``(question, shape)`` — a command expanded, or the text unchanged.

    A command typed with no subject expands to its bare template. That is a
    legitimate question when the conversation already has scope to inherit, and
    the clarify gate asks for scope when it does not — which is exactly the path
    a typed question would take.
    """
    command, rest = parse(text)
    if command is None:
        return (text or "").strip(), ""
    return command.expand(rest), command.shape


def suggestions(text: str) -> Tuple[Command, ...]:
    """The commands matching a partly-typed line, for the composer's menu.

    Empty unless the line actually starts with "/", so the menu never appears
    over a normal question.
    """
    stripped = (text or "").lstrip()
    if not stripped.startswith("/"):
        return ()
    typed = stripped[1:].split(" ", 1)[0].lower()
    if " " in stripped:  # a subject is being typed — the command is settled
        return tuple(c for c in COMMANDS if c.name == typed)
    return tuple(c for c in COMMANDS if c.name.startswith(typed))
