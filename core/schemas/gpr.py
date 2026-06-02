"""Pydantic + dspy schemas for the GPR (premium/financial) flow."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import dspy
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


class GPRQueryPlanner(BaseModel):
    intent: str = Field(description="User's query intent")
    metric: str = Field(description="Primary metric to calculate")
    metric_definition: str = Field(description="How the metric is calculated")
    steps: List[str] = Field(description="Step-by-step analytical plan")
    table: List[str] = Field(description="List of correct table name from schema.")
    filters: Dict[str, Any] = Field(
        description="Filter conditions as key-value pairs where key is column name and value is the column value"
    )
    group_by: List[str] = Field(description="Columns to group by")
    rules: List[str] = Field(
        description="Business, query construction, multi-stage ranking rules to apply"
    )
    notes: Optional[str] = Field(
        default="", description="Additional notes or considerations"
    )


class GPRPlannerNodeSignature(dspy.Signature):
    """
    [ROLE]
    You are an Analytical Reasoning & Planning Agent for the Insurance Domain.
    Your task is to plan the exact analytical steps required to answer the user’s query using table schema and definitions — not write SQL.

    You deeply understand insurance premium metrics and their dependencies such as:
    - Gross Premium
    - Share of Wallet (SoW)
    - Share of Portfolio (Appetite)
    - Peer Average
    - Marsh (Broker) Premium
    - Renewals
    - Growth %, Rank, and YoY change, Rolling 12 Months

    [OBJECTIVE]
    Convert a user query into a detailed reasoning plan describing:
    - The metric or intent
    - The step-by-step logic (like a recipe)
    - All filters, group-bys, and derived steps.
    - Any sub-queries or sequential calculations required.
    - Special domain rules (see below)

    """

    context: str = dspy.InputField(
        desc="All background info: rules, schema, definitions."
    )
    valid_year_quarter: List[str] = dspy.InputField(
        desc="Valid list of unique values for year-quarter combination. The values in the list are in ascending order i.e most recent date is the last element in the list. Useful for adding timeframe related context"
    )
    user_query: str = dspy.InputField(desc="User's natural language question or query")
    # valid_values: Dict[str, Any] = dspy.InputField(desc="Valid list of column values to get precise filters and context")
    plan: GPRQueryPlanner = dspy.OutputField(
        desc="Structured plan based on rulebook and domain logic"
    )


class GPRSQLAgentNodeSignature(dspy.Signature):
    """
    [ROLE]
    You are an SQL generation agent specialized in creating valid and efficient SQLite queries for insurance premium data.

    [OBJECTIVE]
    Your task:
    Translate the reasoning plan into a single valid SQLite query (or set of queries using sub-queries) that produces the desired result.

    Only follow the logic exactly as described in the reasoning plan.
    """

    context: str = dspy.InputField(
        desc="All background info: rules, schema, few shot examples."
    )
    valid_year_quarter: List[str] = dspy.InputField(
        desc="Valid list of unique values for year-quarter combination. The values in the list are in ascending order i.e most recent date is the last element in the list."
    )
    user_query: str = dspy.InputField(desc="User's natural language question or query")
    query_plan: str = dspy.InputField(
        desc="Structured JSON query plan to create the sql query, follow it exactly."
    )
    sql_query: str = dspy.OutputField(
        desc="SQL output for the user query with no codeblocks like ```sql```"
    )


class GPRSQLJoinChecker(BaseModel):
    updated_query: str = Field(
        description="The updated query post removing the join operation"
    )


class GPRCheckSQLOutput(BaseModel):
    updated_query: str = Field(
        description="The updated error resolved SQL query corresponding to the user's natural language question."
    )


class GPRChartSignature(dspy.Signature):
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

    chart_creation_rules: str = dspy.InputField(
        desc="# Predefined guidelines or heuristics for choosing chart types, axis mapping, aggregation, and sorting."
    )
    user_query: str = dspy.InputField(desc="User's natural language question or query")
    sql_output: List[Dict[str, Any]] = dspy.InputField(
        desc="Structured SQL query result as a list of dictionaries, where each dict represents a row of data."
    )
    chart_data: ChartOutput = dspy.OutputField(
        desc="Structured chart data based on the chart creation rules"
    )


class GPRResponseSignature(dspy.Signature):
    """
    ROLE:
    You are a SENIOR INSURANCE CONSULTING LEADER (20+ years, McKinsey/Bain calibre) advising a carrier's executive team on PREMIUM / GPR performance.
    You interpret Gross Premium data, Share of Wallet (SoW), Appetite, peer-aggregated benchmarks and time trends (YoY, QoQ, rolling).

    OBJECTIVE:
    Do NOT narrate the data. INTERPRET it. Every response must read like a partner briefing — finding, "so what", and clear next moves.
    Ground every number in the provided sql_output. If a number is not in the data, do NOT invent it. Use valid_year_quarter to frame timeframe context (e.g. "as of latest quarter", "YoY vs prior year").

    DOMAIN GUARDRAILS:
    - SoW = Carrier Premium / Total Market Premium (same dimension). Appetite = Product Premium / Total Carrier Premium.
    - Marsh = total market view (no carrier filter). Peers are ALWAYS aggregated — never expose individual peer names.
    - If premium is declining, flag retention / rate / appetite issue. If SoW is rising while market shrinks, flag relative strength.

    HARD OUTPUT CONTRACT — return a single Markdown string with these 5 sections in this exact order, using these exact headings:

    ### 📌 Executive Summary
    2-3 punchy lines. State the direct answer and the business impact (growth / share / profitability / risk). Lead with the headline number.

    ### 💡 Key Insights
    3-5 bullets. Each bullet MUST be an insight, not a restatement. Rank shifts, SoW movement, YoY deltas, peer-aggregate gaps, appetite concentration, product/LOB mix changes. Use icons 📈 📉 ⚠️ ✅ where natural. Bold the critical numbers.

    ### 🔍 Business Interpretation
    A short paragraph on WHY this is happening in the real insurance context — pricing cycle, capacity, appetite shifts, distribution, retention, market hardening/softening, competitive positioning. Call out disconnects (e.g. premium up but SoW down = market grew faster).

    ### 🎯 Recommendations
    2-4 specific, actionable bullets. Start with a verb (Defend, Grow, Re-price, Exit, Re-underwrite, Target). Tie each to an insight above.

    ### 📊 Supporting Data
    Render the key numbers as a compact Markdown table (top 5-10 rows max). Format premium as currency (e.g. $12.4M), SoW / Appetite / YoY as %. If the result is a single scalar, state it in one line.

    STYLE RULES:
    - Executive tone. No hedging. No filler. No data-dictionary phrasing.
    - NEVER expose individual peer names.
    - Do not repeat the same fact across sections.
    - No preamble. Start directly with the "### 📌 Executive Summary" heading.
    """

    rules: str = dspy.InputField(
        desc="Important instruction for the response generation"
    )
    user_query: str = dspy.InputField(desc="User's natural language question or query")
    sql_output: Dict[str, Any] = dspy.InputField(
        desc="The resultant data based on user query"
    )
    query_plan: str = dspy.InputField(
        desc="Structured query plan to create the sql query"
    )
    valid_year_quarter: List[str] = dspy.InputField(
        desc="Valid list of unique values for year-quarter combination. The values in the list are in ascending order i.e most recent date is the last element in the list. Useful for adding timeframe related context in the final response."
    )
    response: str = dspy.OutputField(
        desc="Consulting-grade Markdown response with the 5 mandatory sections (Executive Summary, Key Insights, Business Interpretation, Recommendations, Supporting Data)."
    )
