"""The phases a deck build moves through, and the sink it reports them to.

A build is minutes of silence otherwise, and silence is indistinguishable from a hang —
which is exactly how the old synchronous Generate read while it worked. So the builder
*names* the phase it is entering, the bar reads that phase's index, and the wording is
free to change without moving the bar.

A reporter is just a callable, so the build is testable with a list append and the
workspace passes one that writes to its job record. Deliberately the same shape as
:mod:`mom.progress`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple


@dataclass(frozen=True)
class Phase:
    """One step of the build, as the author sees it."""

    id: str
    label: str


# Order IS the progress order; ``percent_done`` reads the index.
PHASES: Tuple[Phase, ...] = (
    Phase("data", "Reading the book"),
    Phase("deck", "Building the deck"),
    Phase("assemble", "Writing the commentary"),
    Phase("render", "Rendering the slides"),
)

_INDEX = {phase.id: i for i, phase in enumerate(PHASES)}


class Reporter(Protocol):
    """Where a running build announces what it is doing."""

    def __call__(self, phase: str, message: str) -> None: ...


def silent(phase: str, message: str) -> None:
    """A reporter that discards everything — the default for tests and scripts."""


def percent_done(phase: str | None, *, finished: bool = False) -> int:
    """How full the progress bar should be while ``phase`` is running."""
    if finished:
        return 100
    if phase not in _INDEX:
        return 0
    # A phase that has *started* is not yet done, so report the floor of its band.
    return round(_INDEX[phase] * 100 / len(PHASES))


def label_for(phase: str | None) -> str:
    """The human label for a phase id."""
    for candidate in PHASES:
        if candidate.id == phase:
            return candidate.label
    return "Working"
