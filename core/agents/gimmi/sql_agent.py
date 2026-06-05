"""GIMMI SQL agent + LangGraph node callables for SQL generation and execution."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import dspy

from core.agents.common import (
    BaseSQLFixerNode,
    log_sql_failure,
    recalled_sql_text,
    record_recovered_sql_fix,
)
from core.data.general import GeneralFunctions
from core.data.valid_values import GetValidData
from core.initialization import Initialization
from core.mcp.tools import execute_sql
from core.observability import log_event, sql_metadata
from core.rules.gimmi import GIMMIRules
from core.schemas.gimmi import GIMMISQLAgentSignature
from core.skills.loader import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)

# Mirror the GPR/Survey deterministic subgraphs: auto-repair + re-run a failing
# GIMMI query up to 3 times before giving up.
_GIMMI_MAX_ATTEMPTS = 3


class GIMMISQLAgentNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(
        self,
        gimmi_schema: List[Dict[str, Any]],
        definitions: Dict[str, str],
        rules: str,
        valid_values: Dict[str, Any],
        recalled_examples: str = "",
    ) -> None:
        super().__init__()
        self.gimmi_schema = gimmi_schema
        self.definitions = definitions
        self.rules = rules
        self.valid_values = valid_values
        # Text block of the user's past verified fixes for similar GIMMI queries.
        self.recalled_examples = recalled_examples

        self.predictor = dspy.ChainOfThought(GIMMISQLAgentSignature)

    def forward(self, user_query: str) -> str:
        # Combine context into a single training/inference context
        context = (
            f"GIMMI Schema:\n{self.gimmi_schema}\n"
            f"Definitions:\n{self.definitions}\n"
            f"Rules:\n{self.rules}\n"
            f"Valid Values:\n{self.valid_values}\n"
        )
        if self.recalled_examples:
            context += f"\n{self.recalled_examples}\n"

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
        recalled_examples=recalled_sql_text(
            state.get("user_id"), "gimmi", question, k=3
        ),
    )
    gimmi_sql_output = gimmi_sql_agent(user_query=question)

    return {"gimmi_sql_query": gimmi_sql_output}


def gimmi_execute_sql(state: AgentState) -> AgentState:
    """Executes the SQL Query via the shared, validated execute_sql tool.

    On error we flag `gimmi_sql_error` so the conditional edge can route into the
    3-attempt fixer loop (mirroring the GPR/Survey subgraphs), instead of
    silently returning a static "try again" string after a single failure.
    """

    sql_query = state["gimmi_sql_query"].strip()
    result = execute_sql("gimmi", sql_query, node="gimmi_execute_sql")

    if result.error:
        return {
            "gimmi_query_result": f"Error executing SQL query: {result.error}",
            "gimmi_sql_error": True,
        }

    record_recovered_sql_fix(state, route="gimmi", working_sql=sql_query)

    logger.debug("GIMMI query fetched %d row(s)", result.row_count)
    return {"gimmi_query_result": result.rows, "gimmi_sql_error": False}


def gimmi_sql_fixer_agent(state: AgentState) -> AgentState:
    """Repair a failing GIMMI query via the shared flow-parameterized fixer."""

    sql_query = state["gimmi_sql_query"].strip()
    question = state["messages"][-1].content
    error_message = state["gimmi_query_result"]

    schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)
    gimmi_schema = schema.get("GIMMI", [])

    log_event(
        logger,
        "sql_fix_attempt",
        route="premium",
        node="gimmi_sql_fixer_agent",
        sql=sql_metadata(sql_query),
        error=str(error_message),
    )

    fixer = BaseSQLFixerNode(flow="gimmi")
    corrected_query = fixer.fix(
        user_query=question,
        schema_tables={"GIMMI": gimmi_schema},
        peer_schema=[],
        sql_query=sql_query,
        error_message=error_message,
        valid_values=GetValidData.gimmi_valid_values,
        definitions=GetValidData.gimmi_definitions,
    )

    return {
        "gimmi_sql_query": corrected_query,
        "gimmi_attempts": 1,
        **log_sql_failure(question, sql_query, error_message, "gimmi"),
    }


def gimmi_end_max_iterations(state: AgentState) -> AgentState:
    log_event(
        logger,
        "sql_fix_max_attempts",
        logging.WARNING,
        route="premium",
        node="gimmi_end_max_iterations",
    )
    return {"gimmi_query_result": "Please try again later!!!"}


def gimmi_execute_sql_router(state: AgentState) -> str:
    """After execution: continue to insight on success, else into the fixer."""
    if not state.get("gimmi_sql_error", False):
        return "gimmi_insight"
    return "gimmi_sql_fixer_agent"


def gimmi_check_attempts_router(state: AgentState) -> str:
    """After a fix: retry while under the attempt cap, else bail out."""
    if state.get("gimmi_attempts", 0) < _GIMMI_MAX_ATTEMPTS:
        return "gimmi_execute_sql"
    return "gimmi_end_max_iterations"
