"""GIMMI SQL agent + LangGraph node callables for SQL generation and execution."""
from __future__ import annotations

from typing import Any, Dict, List

import dspy

from core.data.general import GeneralFunctions
from core.data.valid_values import GetValidData
from core.initialization import Initialization
from core.mcp.tools import execute_sql
from core.rules.gimmi import GIMMIRules
from core.schemas.gimmi import GIMMISQLAgentSignature
from core.skills.loader import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class GIMMISQLAgentNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(
        self,
        gimmi_schema: List[Dict[str, Any]],
        definitions: Dict[str, str],
        rules: str,
        valid_values: Dict[str, Any],
    ) -> None:
        super().__init__()
        self.gimmi_schema = gimmi_schema
        self.definitions = definitions
        self.rules = rules
        self.valid_values = valid_values

        self.predictor = dspy.ChainOfThought(GIMMISQLAgentSignature)

    def forward(self, user_query: str) -> str:
        # Combine context into a single training/inference context
        context = (
            f"GIMMI Schema:\n{self.gimmi_schema}\n"
            f"Definitions:\n{self.definitions}\n"
            f"Rules:\n{self.rules}\n"
            f"Valid Values:\n{self.valid_values}\n"
        )

        result = self.predictor(
            context=context,
            user_query=user_query,
        )

        return result.sql_output


def gimmi_sqlagent_node(state: AgentState) -> AgentState:

    question = state["messages"][-1].content
    schema = GeneralFunctions.get_database_schema(Initialization.engine)
    gimmi_schema = schema.get("GIMMI", [])
    skill_rules = get_skill_loader().sql("gimmi", question)
    query_rules = skill_rules if skill_rules else GIMMIRules.query_rules

    gimmi_sql_agent = GIMMISQLAgentNode(
        gimmi_schema=gimmi_schema,
        definitions=GetValidData.gimmi_definitions,
        rules=query_rules,
        valid_values=GetValidData.gimmi_valid_values,
    )
    gimmi_sql_output = gimmi_sql_agent(user_query=question)

    return {"gimmi_sql_query": gimmi_sql_output}


def gimmi_execute_sql(state: AgentState) -> AgentState:
    """Executes the SQL Query via the shared, validated execute_sql tool."""

    sql_query = state["gimmi_sql_query"].strip()
    result = execute_sql("gimmi", sql_query, node="gimmi_execute_sql")

    if result.error:
        return {"gimmi_query_result": "Please try again later!!!"}

    logger.debug("GIMMI query fetched %d row(s)", result.row_count)
    return {"gimmi_query_result": result.rows}
