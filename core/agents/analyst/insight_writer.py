"""Analyst response adapter. The model selects supported, precomputed claims."""
from __future__ import annotations

from typing import Sequence

from core.answers.grounded import AnswerRequest, GroundedAnswer
from core.answers.writer import write_answer
from core.answers.scope import DisplayScope, defaulted_period


def grounded_insight(*, question: str, route: str, synthesis_focus: str,
                     evidence: list, presentation: str = "prose", shape: str = "analyst",
                     client=None, scope: DisplayScope = (),
                     requirements: Sequence[str] = (),
                     limitations: Sequence[str] = ()) -> GroundedAnswer:
    """Build the answer request for one analyst turn.

    `synthesis_focus` is what the analysis planner decided the answer should lead
    with. It was accepted here and then not passed on, so the planner's choice of
    emphasis died one call short of the writer that needed it and the model had to
    re-infer the angle from the question alone. It now travels into the request
    with the requirements the turn owes and the limitations it could not clear.
    """
    request = AnswerRequest(question, tuple(evidence), shape, presentation, scope,
                            defaulted_period(evidence),
                            synthesis_focus=synthesis_focus or "",
                            requirements=tuple(requirements),
                            limitations=tuple(limitations))
    return write_answer(request, client=client)


def write_insight(**kwargs) -> str:
    """Compatibility entry point for callers that only need the answer text."""
    return grounded_insight(**kwargs).text
