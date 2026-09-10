"""Analyst response adapter. The model selects supported, precomputed claims."""
from __future__ import annotations

from core.answers.grounded import AnswerRequest, GroundedAnswer
from core.answers.writer import write_answer
from core.answers.scope import DisplayScope


def grounded_insight(*, question: str, route: str, synthesis_focus: str,
                     evidence: list, presentation: str = "prose", shape: str = "analyst",
                     client=None, scope: DisplayScope = ()) -> GroundedAnswer:
    request = AnswerRequest(question, tuple(evidence), shape, presentation, scope)
    return write_answer(request, client=client)


def write_insight(**kwargs) -> str:
    """Compatibility entry point for callers that only need the answer text."""
    return grounded_insight(**kwargs).text
