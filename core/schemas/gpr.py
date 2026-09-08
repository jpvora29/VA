"""Pydantic models + signatures for the GPR (premium/financial) flow."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.llm import InputField, OutputField, Signature
from pydantic import BaseModel, Field

from core.schemas.survey import ChartOutput


class GPRQueryNormalizer(BaseModel):
    normalized_query: str = Field(
        description="Updated query, post normalization of values and column names."
    )


class GPRColumnSelectorAgent(BaseModel):
    columns: List[str] = Field(
        description="List of columns to be used as per the user query"
    )


class GPRSQLJoinChecker(BaseModel):
    updated_query: str = Field(
        description="The updated query post removing the join operation"
    )


class GPRChartSignature(Signature):
    """
    [ROLE]
    You are an Expert Data Visualization Analyst specialized in interpreting premium data within the insurance domain.
    Your task is to recommend the most suitable chart type and configuration to effectively represent the user's intent
    based on the provided user query, SQL output, and chart creation rules.

    [OBJECTIVE]
    Analyze the structure and semantics of the survey data (Use the correct field names from the data)
    and determine the optimal visual representation that clearly communicates trends, comparisons, or distributions.

    [RULE]
    STRICTLY assign "x", "y", "series" fields in the Chart Data with the Column Names that are ONLY present in the "sql_output"

    """

    chart_creation_rules: str = InputField(
        desc="# Predefined guidelines or heuristics for choosing chart types, axis mapping, aggregation, and sorting."
    )
    user_query: str = InputField(desc="User's natural language question or query")
    sql_output: List[Dict[str, Any]] = InputField(
        desc="Structured SQL query result as a list of dictionaries, where each dict represents a row of data."
    )
    chart_data: ChartOutput = OutputField(
        desc="Structured chart data based on the chart creation rules"
    )


class GPRResponseSignature(Signature):
    """
    ROLE:
    You are a SENIOR INSURANCE CONSULTING LEADER (20+ years, McKinsey/Bain calibre) advising a carrier's executive team on PREMIUM / GPR performance.
    You interpret Gross Premium data, Share of Wallet (SoW), Appetite, peer-aggregated benchmarks and time trends (YoY, QoQ, rolling).

    OBJECTIVE:
    Do NOT narrate the data. INTERPRET it. Every response must read like a partner briefing — finding, "so what", and clear next moves.
    Ground every number in the provided sql_output. If a number is not in the data, do NOT invent it. Use valid_year_quarter to frame timeframe context (e.g. "as of latest quarter", "YoY vs prior year").

    DOMAIN GUARDRAILS:
    - SoW = Carrier Premium / Total Market Premium (same dimension). Appetite = Product Premium / Total Carrier Premium.
    - Marsh is the BROKER, never a carrier and never a competitor. The premium here is business Marsh PLACED.
      The Marsh book for a slice (no carrier filter) is the carrier's ADDRESSABLE OPPORTUNITY through Marsh —
      what it could compete for. Never call it "the market", "total market premium" or "industry premium".
    - Peers are ALWAYS aggregated — never expose individual peer names.
    - If premium is declining, flag retention / rate / appetite issue. If SoW is rising while market shrinks, flag relative strength.

    OUTPUT SHAPE — the [RESPONSE_SHAPE] input tells you HOW to write THIS
    answer, and it is binding. Follow its structure exactly. The shape is chosen
    from the question, so a lookup gets a sentence and a strategy question gets a
    full argument. Do NOT fall back to a standard five-section template: the same
    headings turn after turn is what makes an assistant read as a form letter.

    Whatever the shape asks for, ground every number in sql_output, and where it
    calls for a table, format premium as currency (e.g. $12.4M) and SoW /
    Appetite / NPS / YoY as %.

    NARRATIVE ARC — wherever the shape has more than one section, the sections
    are a story, not a report (funnel: wide → narrow): start at the broadest
    level, narrow to the segment, attribute or product driving it, and end on the
    sharpest specific finding. Each section answers the question the one above it
    raises. Connect them explicitly ("that decline is concentrated in…", "which
    is why…"). Never present disconnected bullets.

    STYLE RULES:
    - Executive tone. No hedging. No filler. No data-dictionary phrasing.
    - NEVER expose individual peer names.
    - Do not repeat the same fact across sections.
    - No preamble and no restatement of the question. Open with the answer, in the form [RESPONSE_SHAPE] asks for.
    """

    rules: str = InputField(
        desc="Important instruction for the response generation"
    )
    response_shape: str = InputField(
        desc=(
            "The binding structure for THIS answer, chosen from the question by "
            "core.agents.common.answer_shape. Follow it exactly instead of any "
            "default template."
        )
    )
    user_query: str = InputField(desc="User's natural language question or query")
    sql_output: Dict[str, Any] = InputField(
        desc="The resultant data based on user query"
    )
    query_plan: str = InputField(
        desc="Structured query plan to create the sql query"
    )
    valid_year_quarter: List[str] = InputField(
        desc="Valid list of unique values for year-quarter combination. The values in the list are in ascending order i.e most recent date is the last element in the list. Useful for adding timeframe related context in the final response."
    )
    response: str = OutputField(
        desc="Consulting-grade Markdown response, structured exactly as response_shape requires."
    )
