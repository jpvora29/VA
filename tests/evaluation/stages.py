"""Pipeline stages a failure can be attributed to.

Phase 0's acceptance test is that a bad answer can be localized rather than just
labelled bad. Every check declares the stage that owns its failure, and that
attribution is also the repair-dispatch key in Phase 7 — the same vocabulary,
so a check that fires names the component that has to change.

Stages are ordered upstream to downstream. When several checks fail, the
earliest stage is the one worth fixing first: a wrong scope makes every
downstream number wrong too, and repairing the writer would only make a wrong
answer read better.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

INTERPRETATION = "interpretation"
PLANNING = "planning"
RETRIEVAL = "retrieval"
COMPUTATION = "computation"
SELECTION = "selection"
PRESENTATION = "presentation"

#: Upstream to downstream. Index in this tuple is the repair priority.
ORDER: Tuple[str, ...] = (
    INTERPRETATION,
    PLANNING,
    RETRIEVAL,
    COMPUTATION,
    SELECTION,
    PRESENTATION,
)

#: Stage -> the component that owns a repair, mirroring the plan's Phase 7 table.
OWNER = {
    INTERPRETATION: "scope and intent resolver",
    PLANNING: "analysis planner",
    RETRIEVAL: "tool execution layer",
    COMPUTATION: "deterministic calculation layer",
    SELECTION: "claim selection and writer",
    PRESENTATION: "narration and chart binding",
}


@dataclass(frozen=True)
class Attribution:
    """Where a set of failures points, and why that stage was chosen."""

    stage: str
    owner: str
    reason: str

    @property
    def is_localized(self) -> bool:
        return bool(self.stage)


def rank(stage: str) -> int:
    """Repair priority; unknown stages sort last rather than raising."""
    try:
        return ORDER.index(stage)
    except ValueError:
        return len(ORDER)


def localize(failed_stages: Tuple[str, ...]) -> Attribution:
    """The earliest failing stage — the one whose repair can fix the rest.

    An empty input is not an error: a passing run localizes to nothing, and
    callers read `is_localized` rather than catching.
    """
    if not failed_stages:
        return Attribution("", "", "no failures to attribute")
    stage = min(failed_stages, key=rank)
    others = tuple(s for s in dict.fromkeys(failed_stages) if s != stage)
    reason = (
        f"earliest failing stage; {', '.join(others)} may resolve once it is fixed"
        if others
        else "only failing stage"
    )
    return Attribution(stage, OWNER.get(stage, ""), reason)
