"""The phases a run moves through, and the sink it reports them to.

The standalone app inferred progress by grepping the pipeline's stdout for words like
"tag" and "extract", which meant a reworded print silently broke the progress bar.
Here the pipeline *names* the phase it is entering, the bar reads the phase's index,
and prose is free to change.

A reporter is just a callable, so the pipeline is testable with a list append and the
workspace passes one that writes to its job record.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple


@dataclass(frozen=True)
class Phase:
    """One step of the run, as the user sees it."""

    id: str
    label: str


# Order IS the progress order; ``percent_done`` reads the index.
PHASES: Tuple[Phase, ...] = (
    Phase("notes", "Reading the meeting note"),
    Phase("deck", "Reading the deck"),
    Phase("tagging", "Tagging and scoring"),
    Phase("verification", "Verifying"),
    Phase("summary", "Writing the minutes"),
)

_INDEX = {phase.id: i for i, phase in enumerate(PHASES)}


class Reporter(Protocol):
    """Where a running pipeline announces what it is doing."""

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
