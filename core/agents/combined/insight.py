"""Combined Survey + GPR insight synthesis for the 'both' route."""
from __future__ import annotations

import logging

import dspy

from core.agents.common.directives import prose_suppressed
from core.initialization import Initialization
from core.observability import log_event
from core.schemas.combined import CombinedInsightSignature
from core.skills.loader import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class CombinedInsightNode(dspy.Module):
    def __init__(self, rules: str = "") -> None:
        super().__init__()
        self.rules = rules
        self.predictor = dspy.ChainOfThought(CombinedInsightSignature)

    def forward(
        self, user_query, survey_output, gpr_output, survey_reasoning, gpr_reasoning
    ):
        with dspy.context(lm=Initialization.dspy_creative):
            result = self.predictor(
                user_query=user_query,
                rules=self.rules,
                survey_output=survey_output or [],
                gpr_output=gpr_output or [],
                survey_reasoning=survey_reasoning or "",
                gpr_reasoning=gpr_reasoning or "",
            )
        return result.combined_response


def combined_insight(state: AgentState) -> AgentState:
    # Contract: chart_only / table_only renders the artifact alone — skip the
    # fused written analysis and its LLM call.
    if prose_suppressed(state.get("routing_context")):
        log_event(logger, "insight_skipped_by_directive", route="both", node="combined_insight")
        return {"combined_response": ""}

    question = state["messages"][-1].content
    survey_output = state.get("survey_query_result") or []
    gpr_output = state.get("gpr_query_result") or []
    survey_reasoning = state.get("survey_reasoning") or ""
    gpr_reasoning = state.get("gpr_reasoning") or ""

    # The combined answer fuses both lenses, so pull response-scope skills from
    # both flows (cross-flow confidentiality rules dedupe to a single copy).
    rules = get_skill_loader().load_many(["survey", "gpr"], "response", question) or ""
    log_event(
        logger,
        "skill_load",
        route="both",
        node="combined_insight",
        flow="both",
        scope="response",
        used_skills=bool(rules),
    )

    try:
        node = CombinedInsightNode(rules=rules)
        combined = node(
            user_query=question,
            survey_output=survey_output,
            gpr_output=gpr_output,
            survey_reasoning=survey_reasoning,
            gpr_reasoning=gpr_reasoning,
        )
    except Exception as e:
        log_event(
            logger, "combined_insight_error", logging.ERROR, route="both", error=str(e)
        )
        # Graceful fallback — surface whatever single-lens response we already have.
        combined = (
            state.get("survey_response")
            or state.get("gpr_response")
            or "Unable to generate a combined insight for this query. Please try rephrasing."
        )

    return {"combined_response": combined}
