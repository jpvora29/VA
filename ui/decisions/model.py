"""Presentation model for the Decision Board.

The single source of truth mapping a decision's *status* and *priority* to its
colour, icon, and human label. Storage-side canonical values live in
``core.store.decisions`` (``STATUSES`` / ``PRIORITIES``); this module only adds
the UI metadata on top, so render code and callbacks never hand-roll colours or
labels.
"""
from __future__ import annotations

from typing import NamedTuple

from core.store.decisions import PRIORITIES, STATUSES  # re-exported for callers


class StatusMeta(NamedTuple):
    key: str
    label: str
    color: str  # the sticky-note colour name (drives CSS class)
    icon: str  # Bootstrap-icon class


# Column order on the board mirrors ``STATUSES`` in the store layer.
STATUS_META: dict[str, StatusMeta] = {
    "planned": StatusMeta("planned", "Planned", "blue", "bi bi-calendar-event"),
    "under_review": StatusMeta("under_review", "Under review", "yellow", "bi bi-hourglass-split"),
    "approved": StatusMeta("approved", "Approved", "green", "bi bi-check-circle"),
    "blocked": StatusMeta("blocked", "Blocked", "red", "bi bi-x-octagon"),
    "archived": StatusMeta("archived", "Archived", "grey", "bi bi-archive"),
}

PRIORITY_META: dict[str, tuple[str, str]] = {
    # key -> (label, css-suffix)
    "high": ("High", "high"),
    "med": ("Medium", "med"),
    "low": ("Low", "low"),
}

# Statuses a reopened decision can be sent back to (anything but the terminal two).
REOPEN_TARGET = "under_review"


def status_meta(status: str) -> StatusMeta:
    """Lookup with a safe fallback so an unknown status still renders."""
    return STATUS_META.get(status, STATUS_META["planned"])


def status_options() -> list[dict[str, str]]:
    """Dropdown options in board-column order."""
    return [{"label": STATUS_META[s].label, "value": s} for s in STATUSES]


def priority_options() -> list[dict[str, str]]:
    return [{"label": PRIORITY_META[p][0], "value": p} for p in PRIORITIES]


def priority_label(priority: str) -> str:
    return PRIORITY_META.get(priority, PRIORITY_META["med"])[0]


def priority_class(priority: str) -> str:
    return PRIORITY_META.get(priority, PRIORITY_META["med"])[1]
