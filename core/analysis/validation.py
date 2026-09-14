"""Bound chat plans and preserve dependency identity when steps are removed."""
from core.schemas.analysis import AnalysisPlan

#: Steps a chat plan may carry by default.
#:
#: This was 3, which was below the floor of what a performance question needs.
#: The evidence contract for `performance_assessment` alone asks for an annual
#: movement, a product decomposition and a quarterly comparison, and the survey
#: and industry steps sit on top of that — so a 3-step cap silently guaranteed an
#: incomplete answer, and no amount of planner prompting could recover it. The
#: planner signature already asks for "2-5 high-value lenses"; the cap now sits
#: above that range instead of contradicting it.
MAX_CHAT_LENSES = 6

#: The hard ceiling no contract can push past. A plan is a budget as well as a
#: specification: past this the marginal step costs a model call and a query and
#: buys very little, and a runaway planner is a latency incident.
MAX_PLAN_STEPS = 8


def plan_limit(contract=None) -> int:
    """How many steps this turn's plan may carry.

    A turn whose evidence contract asks for more than the default gets more,
    because the alternative is planning fewer steps than the answer is required
    to contain. Everything stays under `MAX_PLAN_STEPS`.
    """
    required = len(getattr(contract, "selected", ()) or ())
    return min(max(MAX_CHAT_LENSES, required), MAX_PLAN_STEPS)


def validate_plan(plan: AnalysisPlan, valid_lenses: set[str], *, limit: int | None = None) -> AnalysisPlan:
    kept, indices, seen = [], {}, set()
    for original, step in enumerate(plan.derived):
        if limit is not None and len(kept) >= limit:
            break
        identity = (step.lens, step.sub_question.strip().casefold())
        if step.lens not in valid_lenses or not step.sub_question.strip() or identity in seen:
            continue
        if any(dependency not in indices for dependency in step.depends_on):
            continue
        indices[original] = len(kept)
        kept.append(step.model_copy(update={"depends_on": [indices[d] for d in step.depends_on]}))
        seen.add(identity)
    return AnalysisPlan(derived=kept, synthesis_focus=plan.synthesis_focus)
