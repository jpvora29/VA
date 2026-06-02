"""GIMMI response node + gating callable for the conditional GIMMI branch."""
from __future__ import annotations

import re

import dspy

from core.rules.gimmi import GIMMIRules
from core.schemas.gimmi import GIMMIResponseSignature
from core.skills import get_skill_loader
from core.state.agent_state import AgentState


class GIMMIResponseNode(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(GIMMIResponseSignature)

    def forward(self, user_query, rules, sql_output) -> str:
        result = self.predictor(
            rules=rules, user_query=user_query, sql_output=sql_output
        )

        return result.gimmi_response


def gimmi_insight(state: AgentState) -> AgentState:
    question = state["messages"][-1].content
    query_result = state["gimmi_query_result"]
    skill_rules = get_skill_loader().response("gimmi", question)
    response_rules = skill_rules if skill_rules else GIMMIRules.response_rules

    responseNode = GIMMIResponseNode()
    gimmi_response = responseNode(
        user_query=question, rules=response_rules, sql_output=query_result
    )

    print(f"Gimmi Response : {gimmi_response}")

    return {"gimmi_response": gimmi_response}


def check_if_gimmi_required(state: AgentState):
    question = state["messages"][-1].content

    # Pattern that matches any of your keywords
    pattern = r"\b(benchmark(?:ing)?|peer comparison|market analysis|market|region)\b"

    if re.search(pattern, question, re.IGNORECASE):
        print("GIMMI Data Required")

        return "gimmi_sqlagent_node"
    else:
        return "end"
