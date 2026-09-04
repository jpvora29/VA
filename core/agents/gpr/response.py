"""GPR response node + insight callable wired into the graph."""
from __future__ import annotations

from typing import Any, Dict, List

import logging

try:
    from config.valid_values_config import *  # noqa: F401,F403 - legacy valid_year_quarter_gpr
except ModuleNotFoundError:
    valid_year_quarter_gpr = []
from core.agents.common.analysis_rules import with_analysis_rules
from core.agents.common.directives import prose_suppressed
from core.llm import Predictor
from core.observability import log_event
from core.rules.gpr import GPRRules
from core.schemas.gpr import GPRResponseSignature
from core.skills.loader import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class GPRResponseNode:
    """Writes the premium analysis from the plan and the SQL output.

    Creative tier: this is the prose the user reads, so phrasing should vary
    naturally rather than repeat a template turn after turn.
    """

    def __init__(self, predictor: Predictor | None = None) -> None:
        self.predictor = predictor or Predictor(
            with_analysis_rules(GPRResponseSignature), tier="creative", reasoning=True,
            label="gpr_insight", node="gpr",
        )

    def __call__(
        self,
        user_query: str,
        query_plan: str,
        rules: str,
        valid_year_quarter: List[str],
        sql_output: Dict[str, Any],
    ) -> str:

        # Combine context into a single training/inference context

        result = self.predictor(
            rules=rules,
            user_query=user_query,
            query_plan=query_plan,
            valid_year_quarter=valid_year_quarter,
            sql_output=sql_output,
        )
        return result.response


# Stateless module/predictor — instantiate once and reuse across turns.
_GPR_RESPONSE_NODE = GPRResponseNode()


def gpr_insight(state: AgentState) -> AgentState:
    # Contract: a chart_only / table_only turn renders the artifact alone — skip
    # the written premium analysis (and its LLM call) entirely.
    if prose_suppressed(state.get("routing_context")):
        log_event(logger, "insight_skipped_by_directive", route="premium", node="gpr_insight")
        return {"gpr_response": ""}

    question = state["messages"][-1].content
    reasoning_plan = state["gpr_reasoning"]
    query_output = state["gpr_query_result"]
    skill_rules = get_skill_loader().response("gpr", question)
    response_rules = skill_rules if skill_rules else GPRRules.response_rules

    try:
        gpr_response = _GPR_RESPONSE_NODE(
            user_query=question,
            query_plan=reasoning_plan,
            rules=response_rules,
            valid_year_quarter=valid_year_quarter_gpr,
            sql_output=query_output,
        )
    except Exception as exc:
        log_event(
            logger, "gpr_insight_error", logging.ERROR, route="premium", error=str(exc)
        )
        gpr_response = (
            "I couldn't compose the premium analysis for this query. "
            "Please try rephrasing or narrowing the filters."
        )

    return {"gpr_response": gpr_response}
