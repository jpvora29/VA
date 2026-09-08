"""Survey response node + insight/overflow callables wired into the graph."""
from __future__ import annotations

import logging
from typing import Any, Dict

from core.agents.common.analysis_rules import with_analysis_rules
from core.agents.common.answer_shape import shape_contract
from core.agents.common.directives import answer_shape, prose_suppressed
from core.llm import Predictor
from core.observability import log_event
from core.rules.survey import SurveyRules
from core.schemas.survey import SurveyResponseSignature
from core.skills.loader import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class SurveyResponseNode:
    """Writes the broker-perception analysis from the plan and the SQL output.

    Creative tier: this is prose the user reads, so phrasing varies naturally
    instead of repeating a template turn after turn.
    """

    def __init__(self, predictor: Predictor | None = None) -> None:
        self.predictor = predictor or Predictor(
            with_analysis_rules(SurveyResponseSignature), tier="creative", reasoning=True,
            label="survey_insight", node="survey",
        )

    def __call__(
        self,
        user_query: str,
        query_plan: str,
        rules: str,
        response_shape: str,
        sql_output: Dict[str, Any],
    ) -> str:

        # Combine context into a single training/inference context

        result = self.predictor(
            rules=rules,
            response_shape=response_shape,
            user_query=user_query,
            query_plan=query_plan,
            sql_output=sql_output,
        )
        return result.response


# Stateless module/predictor — instantiate once and reuse across turns.
_SURVEY_RESPONSE_NODE = SurveyResponseNode()


def survey_data_overflow(state: AgentState) -> AgentState:
    return {
        "survey_data_overflow_msg": "The resultant output for the query is too big to display on the UI, please be more specific for the output to get display. You can check the resultant data from the below Excel file."
    }


def survey_data_overflow_route(state: AgentState):
    logger.debug("Survey overflow value: %s", state.get("survey_overflow"))
    if not state.get("survey_overflow", False):
        "survey_insight"
    else:
        "survey_data_overflow"


def survey_insight(state: AgentState) -> AgentState:
    # Contract: chart_only / table_only renders the artifact alone — skip the
    # written survey analysis and its LLM call.
    if prose_suppressed(state.get("routing_context")):
        log_event(logger, "insight_skipped_by_directive", route="survey", node="survey_insight")
        return {"survey_response": ""}

    question = state["messages"][-1].content
    query_output = state["survey_query_result"]
    reasoning_plan = state["survey_reasoning"]
    skill_rules = get_skill_loader().response("survey", question)
    response_rules = skill_rules if skill_rules else SurveyRules.response_rules

    # The shape this question calls for (a lookup gets a sentence, a "why"
    # gets ranked drivers). Resolved once here and handed to the writer as its
    # binding contract, so the rails stop emitting the same five headings.
    shape = shape_contract(answer_shape(state.get("routing_context")))


    try:
        survey_response = _SURVEY_RESPONSE_NODE(
            user_query=question,
            query_plan=reasoning_plan,
            rules=response_rules,
            response_shape=shape,
            sql_output=query_output,
        )
    except Exception as exc:
        log_event(
            logger, "survey_insight_error", logging.ERROR, route="survey", error=str(exc)
        )
        survey_response = (
            "I couldn't compose the survey analysis for this query. "
            "Please try rephrasing or narrowing the filters."
        )

    return {"survey_response": survey_response}
