"""Unified, typed schemas shared by the GPR and Survey analytical flows.

These replace the near-duplicate planner / SQL-agent signatures that used to live
in `core.schemas.gpr` and `core.schemas.survey`. Both flows now share:

- `AnalyticalPlan`     — the structured plan produced by the planner (superset of the
                          old `GPRQueryPlanner` / `SurveyQueryPlanner`).
- `PlannerSignature`   — typed planner contract (schema/definitions/valid_values/
                          valid_year_quarter/routing_context/rules/user_query -> plan).
- `SQLAgentSignature`  — typed SQL-generation contract.
- `SQLFixerOutput`     — single corrected-query model used by the shared SQL fixer.

Domain differences (SoW/SoP vs sections/attributes) are supplied through the `rules`
field (skills + `core.rules.*`), NOT through separate signatures — so one code path
serves both flows.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.llm import InputField, OutputField, Signature
from pydantic import BaseModel, Field

from core.schemas.routing import RoutingContext


class PrimitiveCall(BaseModel):
    """One deterministic analytics primitive the planner wants computed.

    The planner emits these for metrics the primitive library covers (rank, SoP,
    SoW, YoY, peer average, whitespace, …) instead of describing SQL; the analytics
    orchestrator runs them deterministically. Filters/group_by are grounded the
    same way as the rest of the plan.
    """

    name: str = Field(
        description="Registered primitive name, e.g. 'compute_rank', 'find_whitespace'."
    )
    metric: str = Field(
        default="",
        description="Measure to compute over, e.g. 'premium' or 'score'.",
    )
    group_by: List[str] = Field(
        default_factory=list,
        description="Dimension cut column(s), e.g. ['Product_Line'].",
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Call-specific filters (merged over the turn's shared scope).",
    )


class AnalyticalPlan(BaseModel):
    """Structured, flow-agnostic analytical plan emitted by the planner.

    The `filters` key name + shape is preserved because
    `GeneralFunctions.clean_sql_output` reads it. `tables` replaces the old singular
    `table`; downstream only ever reads it as free text inside the JSON string.
    """

    intent: str = Field(description="User's query intent")
    metric: str = Field(description="Primary metric to calculate")
    metric_definition: str = Field(description="How the metric is calculated")
    steps: List[str] = Field(description="Step-by-step analytical plan")
    tables: List[str] = Field(
        default_factory=list,
        description="List of correct table name(s) from the schema.",
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Filter conditions as key-value pairs where key is the column name and "
            "value is the column value."
        ),
    )
    group_by: List[str] = Field(
        default_factory=list, description="Columns to group by"
    )
    timeframe: str = Field(
        default="",
        description=(
            "Concrete timeframe the plan assumes (e.g. '2024', '2023-2024', "
            "'last 12 months to latest quarter'). Resolve relative terms using "
            "routing_context.timeframe_hint and valid_year_quarter."
        ),
    )
    rules: List[str] = Field(
        default_factory=list,
        description="Business, query construction, multi-stage ranking rules to apply",
    )
    notes: Optional[str] = Field(
        default="", description="Additional notes or considerations"
    )
    primitives: List[PrimitiveCall] = Field(
        default_factory=list,
        description=(
            "Deterministic primitive calls for metrics the analytics library covers "
            "(rank, share of portfolio/wallet, YoY, peer average, whitespace, …). "
            "Empty when the query needs ad-hoc SQL instead — the orchestrator then "
            "falls back to the SQL agent. Additive: leaving this empty preserves the "
            "existing SQL path exactly."
        ),
    )


class PlannerSignature(Signature):
    """
    [ROLE]
    You are an Analytical Reasoning & Planning Agent for the Insurance Domain.
    Your task is to plan the exact analytical steps required to answer the user's
    query using the table schema and definitions — NOT to write SQL.

    You understand insurance metrics and their dependencies (Gross Premium, Share of
    Wallet (SoW), Share of Portfolio / Appetite, Peer Average, Marsh/Broker premium,
    Renewals, Growth %, Rank, YoY change, Rolling 12 Months) as well as survey metrics
    (Score, NPS, sections, attributes, segments) — apply only what the supplied `rules`
    and schema indicate for the current flow.

    [OBJECTIVE]
    Convert the user query into a detailed reasoning plan describing:
    - The metric or intent.
    - The step-by-step logic (like a recipe).
    - All filters, group-bys, derived steps, and any sub-queries / sequential
      calculations required.
    - The concrete timeframe (resolve relative terms via routing_context.timeframe_hint
      and valid_year_quarter — do NOT re-derive what is already provided).
    - Special domain rules (see the `rules` input).

    [CONTEXT INHERITANCE]
    routing_context carries inherited carrier/country/year/metric from prior turns and
    the turn's intent_type. When the current query is a followup/drilldown that omits a
    filter, INHERIT it from routing_context — never invent filters not present in the
    query or routing_context.

    [GROUNDING]
    Use `valid_values` to pin filter values to exact valid entries; never put a column or
    value into the plan that is absent from `table_schema` / `valid_values`.
    """

    table_schema: Dict[str, Any] = InputField(
        desc="Schema for this flow as {table_name: [column metadata]}."
    )
    definitions: Dict[str, str] = InputField(
        desc="Business definitions for the columns of the relevant table(s)."
    )
    valid_values: Dict[str, Any] = InputField(
        desc="Valid column values, used to pin filters to exact entries and avoid hallucination."
    )
    valid_year_quarter: List[str] = InputField(
        desc=(
            "Valid unique year (or year+quarter) values in ascending order; the most "
            "recent period is the last element. Use it to resolve timeframe context."
        )
    )
    routing_context: RoutingContext = InputField(
        desc=(
            "Structured routing + inheritance context from the context filler: inherited "
            "filters, timeframe_hint, and intent_type. Use it to carry prior-turn context."
        )
    )
    rules: str = InputField(
        desc="Flow-specific business / planning rules and worked examples."
    )
    user_query: str = InputField(desc="User's natural language question or query")
    plan: AnalyticalPlan = OutputField(
        desc="Structured analytical plan based on the rules, schema, and domain logic."
    )


class SQLAgentSignature(Signature):
    """
    [ROLE]
    You are an SQL generation agent specialized in creating valid and efficient SQLite
    queries for insurance data (premium/financial OR survey, per the supplied schema).

    [OBJECTIVE]
    Translate the reasoning plan into a single valid SQLite query (or a set of queries
    using sub-queries) that produces the desired result. Follow the logic exactly as
    described in the query_plan. Use `valid_values` to keep filter values exact and
    `valid_year_quarter` to frame timeframe filters.
    """

    table_schema: Dict[str, Any] = InputField(
        desc="Schema for this flow as {table_name: [column metadata]}."
    )
    rules: str = InputField(
        desc="Flow-specific query-construction rules."
    )
    few_shot: Any = InputField(
        desc="Worked few-shot query examples for this flow (may be empty)."
    )
    valid_values: Dict[str, Any] = InputField(
        desc="Valid column values, used to keep filter values exact."
    )
    valid_year_quarter: List[str] = InputField(
        desc=(
            "Valid unique year (or year+quarter) values in ascending order; the most "
            "recent period is the last element."
        )
    )
    query_plan: str = InputField(
        desc="Structured JSON query plan to build the SQL query — follow it exactly."
    )
    user_query: str = InputField(desc="User's natural language question or query")
    sql_query: str = OutputField(
        desc="SQL output for the user query with no codeblocks like ```sql```"
    )


class SQLFixerOutput(BaseModel):
    """Corrected SQL produced by the shared SQL fixer (both flows)."""

    updated_query: str = Field(
        description=(
            "The error-resolved SQL query corresponding to the user's natural language "
            "question."
        )
    )
