"""GPR graph adapter for the shared, fact-backed answer pipeline."""
from __future__ import annotations

from core.answers.response_pipeline import write_response
from core.state.agent_state import AgentState


def gpr_insight(state: AgentState) -> dict:
    return write_response(state, "gpr_response", ("gpr",))
