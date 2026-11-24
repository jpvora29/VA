"""A lookup is a one-step plan.

The analyst planner is a model call that picks two to five lenses. A lookup owes
one value or one breakdown, so its plan is known without asking: a single step
that answers the literal question. Building it here keeps the planner's model
call for questions that actually need a plan, and lets every data turn run
through the same pipeline (see `core.turn.pipeline`).
"""

from __future__ import annotations

from typing import Any

from core.schemas.analysis import AnalysisPlan, DerivedAnalysis

#: The lens of a lookup step. No lens file exists for it on purpose: the solver
#: falls back to "answer the sub-question directly", which is the instruction a
#: lookup needs.
LOOKUP_LENS = "lookup"


def is_lookup_turn(routing_context: Any) -> bool:
    """Whether the intent classifier explicitly left this turn at lookup depth.

    No routing context means nothing decided the depth, so it is not a lookup.
    """
    depth = getattr(routing_context, "analysis_depth", None)
    if depth is None and isinstance(routing_context, dict):
        depth = routing_context.get("analysis_depth")
    return bool(depth) and depth != "analytical"


def lookup_plan(question: str) -> AnalysisPlan:
    """One step, answering the question as asked."""
    return AnalysisPlan(
        derived=[
            DerivedAnalysis(
                lens=LOOKUP_LENS,
                sub_question=question,
                rationale="A lookup owes one value or one breakdown.",
            )
        ],
        synthesis_focus="Answer the question directly.",
    )


def is_lookup_plan(plan: AnalysisPlan | None) -> bool:
    return (
        plan is not None
        and len(plan.derived) == 1
        and plan.derived[0].lens == LOOKUP_LENS
    )
