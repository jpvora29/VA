"""SURVEY graph adapter for the shared, fact-backed answer pipeline."""
from __future__ import annotations

from core.answers.response_pipeline import write_response
from core.state.agent_state import AgentState


def survey_insight(state: AgentState) -> dict:
    return write_response(state, "survey_response", ("survey",))


def survey_data_overflow(state: AgentState) -> dict:
    return {"survey_data_overflow_msg": "There are too many results to display. Narrow the filters or download the data."}


def survey_data_overflow_route(state: AgentState) -> str:
    return "survey_data_overflow" if state.get("survey_overflow", False) else "survey_insight"
