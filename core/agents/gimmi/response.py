"""GIMMI response node + gating callable for the conditional GIMMI branch."""
from __future__ import annotations

import logging
import re

import dspy

from core.agents.common.directives import prose_suppressed
from core.observability import log_event
from core.rules.gimmi import GIMMIRules
from core.schemas.gimmi import GIMMIResponseSignature
from core.skills.loader import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class GIMMIResponseNode(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(GIMMIResponseSignature)

    def forward(self, user_query, rules, sql_output) -> str:
        result = self.predictor(
            rules=rules, user_query=user_query, sql_output=sql_output
        )

        return result.gimmi_response


# Stateless module/predictor — instantiate once and reuse across turns. GIMMI
# stays deterministic (default LM) since it is factual market-rate data.
_GIMMI_RESPONSE_NODE = GIMMIResponseNode()


def gimmi_insight(state: AgentState) -> AgentState:
    # Contract: chart_only / table_only renders the artifact alone — skip the
    # written market-rate commentary (the premium answer also drops its prose).
    if prose_suppressed(state.get("routing_context")):
        log_event(logger, "insight_skipped_by_directive", route="premium", node="gimmi_insight")
        return {"gimmi_response": ""}

    question = state["messages"][-1].content
    query_result = state["gimmi_query_result"]
    skill_rules = get_skill_loader().response("gimmi", question)
    response_rules = skill_rules if skill_rules else GIMMIRules.response_rules

    try:
        gimmi_response = _GIMMI_RESPONSE_NODE(
            user_query=question, rules=response_rules, sql_output=query_result
        )
    except Exception as exc:
        log_event(
            logger, "gimmi_insight_error", logging.ERROR, route="premium", error=str(exc)
        )
        gimmi_response = ""

    logger.debug("GIMMI response: %s", gimmi_response)

    return {"gimmi_response": gimmi_response}


def check_if_gimmi_required(state: AgentState):
    question = state["messages"][-1].content

    # Pattern that matches any of your keywords
    pattern = r"\b(benchmark(?:ing)?|peer comparison|market analysis|market|region)\b"

    if re.search(pattern, question, re.IGNORECASE):
        logger.debug("GIMMI data required for query")
        return "gimmi_sqlagent_node"
    return "end"
