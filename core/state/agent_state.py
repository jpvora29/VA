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

    # Owning user (from the lightweight login). Threaded in from the UI so memory
    # nodes can scope episodic recall/record per user. Optional so non-UI callers
    # (tests, MCP) still type-check.
    user_id: Optional[str]

    # Verified SQL error→fix breadcrumbs for this turn. Each fixer node appends a
    # {failed_sql, error, route} entry; on a successful retry the execute node
    # persists the pair to episodic memory. `add` so entries accumulate across the
    # fixer loop instead of overwriting.
    sql_error_log: Annotated[List, add]

    # Structured routing context produced by ContextFillingAgent. Consumed by
    # the rephraser (for inheritance) and the router (for deterministic
    # dispatch). Optional so first-turn / fallback paths still type-check.
    routing_context: Optional[RoutingContext]

    # HITL clarification (workflow path). `clarify_decide` sets a pending MCQ
    # payload (dict) when the turn is genuinely ambiguous; `clarify_gate`
    # interrupts on it and stores the user's answer in `clarification`.
    clarify_question: Optional[Dict]
    clarification: str

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

    # Up to 3 chart specs produced by the analyst agent's chart-picker, each
    # {"title", "rows", "chart_data"}. The deterministic rails use the per-flow
    # *_chart fields above; the analyst path carries its own multi-chart list.
    analyst_charts: List

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
    gimmi_sql_error: bool
    gimmi_attempts: Annotated[int, add]

    # Suggested next questions produced by the terminal follow-up node.
    followup_questions: List[str]
