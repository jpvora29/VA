"""Bound chat plans and preserve dependency identity when steps are removed."""
from core.schemas.analysis import AnalysisPlan

MAX_CHAT_LENSES = 3


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
