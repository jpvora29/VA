"""GPR response node + insight callable wired into the graph."""
from __future__ import annotations

from typing import Any, Dict, List

import dspy

from config.valid_values_config import *  # noqa: F401,F403 - preserves legacy globals (valid_year_quarter_gpr)
from core.initialization import Initialization
from core.rules.gpr import GPRRules
from core.schemas.gpr import GPRResponseSignature
from core.skills import get_skill_loader
from core.state.agent_state import AgentState


class GPRResponseNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(GPRResponseSignature)

    def forward(
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


def gpr_insight(state: AgentState) -> AgentState:
    question = state["messages"][-1].content
    reasoning_plan = state["gpr_reasoning"]
    query_output = state["gpr_query_result"]
    skill_rules = get_skill_loader().response("gpr", question)
    response_rules = skill_rules if skill_rules else GPRRules.response_rules

    responseNode = GPRResponseNode()
    gpr_response = responseNode(
        user_query=question,
        query_plan=reasoning_plan,
        rules=response_rules,
        valid_year_quarter=valid_year_quarter_gpr,
        sql_output=query_output,
    )

    Initialization.log_prompt_cache_usage(response=gpr_response, label="gpr_insight")

    # state['gpr_response'] = gpr_response

    return {"gpr_response": gpr_response}
