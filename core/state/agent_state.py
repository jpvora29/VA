"""Main chatbot agent state.

This TypedDict is the chat workflow state for the Survey + GPR + GIMMI flow.
Pitch/report generation uses `core.state.pitch_state.PitchAgentState` so the
two workflows can evolve independently.
"""
from __future__ import annotations

from operator import add
from typing import Dict, List, Literal, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from core.schemas.routing import RoutingContext


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Structured routing context produced by ContextFillingAgent. Consumed by
    # the rephraser (for inheritance) and the router (for deterministic
    # dispatch). Optional so first-turn / fallback paths still type-check.
    routing_context: Optional[RoutingContext]

    survey_reasoning: str
    gpr_reasoning: str

    rephrased_user_query: str

    survey_sql_query: str
    gpr_sql_query: str
    combined_sql_query: str

    survey_query_result: List
    gpr_query_result: List
    combined_result: List

    survey_response: str
    gpr_response: str
    combined_response: str

    survey_chart: Dict
    gpr_chart: Dict
    combined_chart: Dict

    current_route: Literal["survey", "premium", "both", "fallback"]
    out_of_scope_answer: str

    survey_sql_error: bool
    gpr_sql_error: bool

    survey_cols: List[str]
    gpr_cols: List[str]

    survey_attempts: Annotated[int, add]
    gpr_attempts: Annotated[int, add]

    survey_data_overflow_msg: str
    gpr_data_overflow_msg: str

    survey_overflow: bool
    gpr_overflow: bool

    gimmi_sql_query: str
    gimmi_query_result: List
    gimmi_response: str

    # Suggested next questions produced by the terminal follow-up node.
    followup_questions: List[str]
