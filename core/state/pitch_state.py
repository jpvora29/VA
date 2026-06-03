"""Pitch builder agent state.

Pitch uses its own LangGraph state and checkpointer. It intentionally carries
the SQL workflow fields needed to run the same Survey + GPR + GIMMI graph as
chat, plus report-generation fields used by the docx workflow.
"""
from __future__ import annotations

from operator import add
from typing import Any, List, Literal, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from core.schemas.routing import RoutingContext


class PitchQuestionResult(TypedDict, total=False):
    question: str
    answer: str
    pitch_route: str
    pitch_sql_query: Any
    pitch_query_result: Any
    error: str


class PitchAgentState(TypedDict, total=False):
    # Same analytical workflow surface as AgentState, kept separate so chat-only
    # additions do not leak into report generation.
    messages: Annotated[Sequence[BaseMessage], add_messages]
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

    # Pitch/report workflow fields.
    pitch_thread_id: str
    pitch_theme: str
    pitch_theme_label: str
    pitch_filters: dict[str, Any]
    pitch_questions: list[str]
    pitch_answers: dict[str, str]
    pitch_question_results: list[PitchQuestionResult]
    pitch_extracted_insights: list[dict[str, Any]]
    pitch_top_kpis: dict[str, Any]
    pitch_narrative_arc: dict[str, Any]
    pitch_query_markdown: dict[str, str]
    # pitch_synthesized_insights: dict[str, Any]
    # pitch_data_summary: dict[str, Any]
    pitch_report_prompt: str
    pitch_report_summary: str
    pitch_report_path: str
