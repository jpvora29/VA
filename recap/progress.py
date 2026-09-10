"""The stages a recap run moves through, and the sink it reports them to.

Two levels, because the run has two audiences:

    :data:`STAGES`   the stages the pipeline actually moves through, each with the
                     percentage the bar stands at while it is running. The pipeline
                     names the stage it is *entering*; prose is free to change.
    :data:`PHASES`   the six the rail shows. A step per stage down the left edge is a
                     list, not a progress indicator — each phase owns a run of
                     stages, so the rail lights up while the bar keeps moving.

The standalone app inferred progress from hard-coded percentages passed at each call
site, so re-ordering a stage silently broke the bar. Here order IS the progress order
and a stage id is the only thing crossing the boundary.

A reporter is just a callable, so the pipeline is testable with a list append and the
workspace passes one that writes to its job record.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Tuple


@dataclass(frozen=True)
class Phase:
    """One step of the run, as the rail shows it."""

    id: str
    label: str
    icon: str


@dataclass(frozen=True)
class Stage:
    """One thing the pipeline does, and where the bar stands while it does it."""

    id: str
    label: str
    percent: int
    phase: str


# The rail's steps, in order.
PHASES: Tuple[Phase, ...] = (
    Phase("read", "Reading the decks", "bi-easel"),
    Phase("filter", "Filtering noise", "bi-funnel"),
    Phase("enrich", "Enriching insights", "bi-stars"),
    Phase("classify", "Classifying", "bi-tags"),
    Phase("write", "Writing the recap", "bi-journal-richtext"),
    Phase("render", "Rendering the deck", "bi-file-earmark-slides"),
)

# Order IS the progress order. Percentages are the floor of each stage's band: a
# stage that has STARTED is not yet done.
STAGES: Tuple[Stage, ...] = (
    Stage("staging", "Preparing the uploaded decks", 5, "read"),
    Stage("extracting", "Extracting slides", 15, "read"),
    Stage("filtering", "Filtering noise", 28, "filter"),
    Stage("grouping", "Building content units", 38, "filter"),
    Stage("enriching", "Enriching insights", 55, "enrich"),
    # Umbrella, sub-category and action-item classification run concurrently per
    # insight, so they are one stage: reporting three would mean reporting them
    # per insight, and the bar would thrash rather than progress.
    Stage("classifying", "Classifying insights", 70, "classify"),
    Stage("storing", "Assembling the insight store", 90, "classify"),
    Stage("recap", "Generating the recap", 96, "write"),
    Stage("rendering", "Rendering the PPTX", 99, "render"),
)

_STAGES: Dict[str, Stage] = {stage.id: stage for stage in STAGES}
_PHASE_INDEX: Dict[str, int] = {phase.id: i for i, phase in enumerate(PHASES)}


class Reporter(Protocol):
    """Where a running pipeline announces what it is doing."""

    def __call__(self, stage: str, message: str = "") -> None: ...


def silent(stage: str, message: str = "") -> None:
    """A reporter that discards everything — the default for tests and scripts."""


def percent_done(stage: Optional[str], *, finished: bool = False) -> int:
    """How full the progress bar should be while ``stage`` is running."""
    if finished:
        return 100
    found = _STAGES.get(stage or "")
    return found.percent if found else 0


def label_for(stage: Optional[str]) -> str:
    """The human label for a stage id."""
    found = _STAGES.get(stage or "")
    return found.label if found else "Working"


def phase_for(stage: Optional[str]) -> Optional[str]:
    """Which rail step a stage belongs to."""
    found = _STAGES.get(stage or "")
    return found.phase if found else None


def phase_index(phase: Optional[str]) -> Optional[int]:
    """Where a phase sits in the rail, or None when it names no phase."""
    return _PHASE_INDEX.get(phase or "")
