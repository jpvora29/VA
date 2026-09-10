"""GIMMI graph adapter for the shared, fact-backed answer pipeline."""
from __future__ import annotations

import re

from core.answers.response_pipeline import write_response
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


def gimmi_insight(state: AgentState) -> dict:
    return write_response(state, "gimmi_response", ("gimmi",))


def check_if_gimmi_required(state: AgentState):
    question = state["messages"][-1].content

    # Pattern that matches any of your keywords
    pattern = r"\b(benchmark(?:ing)?|peer comparison|market analysis|market|region)\b"

    if re.search(pattern, question, re.IGNORECASE):
        logger.debug("GIMMI data required for query")
        return "gimmi_sqlagent_node"
    return "end"
