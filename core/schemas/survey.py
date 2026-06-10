"""Pydantic + dspy schemas for the Survey flow.

Contains all typed contracts for survey planner, SQL agent, chart, response,
plus the shared `ChartOutput` model (used by both Survey and GPR chart nodes).
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import dspy
from pydantic import BaseModel, Field


class SurveyQueryNormalizer(BaseModel):
    normalized_query: str = Field(
        description="Updated query post normalization of values and column names."
    )


class SurveyColumnSelectorAgent(BaseModel):
    columns: List[str] = Field(
        description="List of columns to be used as per the user query"
    )


class SurveySQLJoinChecker(BaseModel):
    updated_query: str = Field(
        description="The updated query post removing the join operation"
    )


class ChartOutput(BaseModel):
    """Structured output representing chart configuration for visualization."""

    chart_type: Literal[
        "bar", "line", "pie", "donut", "scatter", "waterfall", "combo", "none"
    ] = Field(
        ...,
        description=(
            "Type of chart to generate. One of: 'bar', 'line', 'pie', 'donut', "
            "'scatter', 'waterfall' (a bridge/movement decomposition), 'combo' "
            "(bars for an absolute measure + a line for a rate/% on a secondary "
            "axis), or 'none' (single scalar / nothing chartable). Choose based on "
            "the metric and intent of the user query."
        ),
    )

    x: str = Field(
        ...,
        description=(
            "Column or field name to be plotted on the X-axis. "
            "Typically represents categorical or time-based data. "
            # "Typically represents categorical or time-based data. (Use the exact name as in the **data i.e sql_output**)'."
            "Ensure to use the **EXACT NAME** present in the **sql_output** "
        ),
    )

    y: List[str] = Field(
        ...,
        description=(
            "Column or field names to be plotted on the Y-axis. "
            "Represents the measure or numerical value. "
            # "Represents the measure or numerical value. (Use the exact name as in the **data i.e sql_output**)'"
            "Ensure to use the **EXACT NAME** present in the **sql_output** "
        ),
    )

    series: List[str] = Field(
        ...,
        description=(
            "Optional categorical field used to create multiple series within the same chart. "
            "Values of this column appear in the legend and determine color grouping. "
            "For example, when plotting Score by Month, 'Carrier_Group' or 'Segment' can be the series "
            "to show separate lines or bars for each group."
            "Ensure to use the **EXACT NAME** present in the **sql_output** "
        ),
    )

    bar_mode: List[str] = Field(
        ...,
        description=(
            "If the chart_type is 'Bar', only then this parameter should be filled with either 'group' or 'stack'"
            "Assert that, number of elements in 'series' and 'bar_mode' are same"
        ),
    )

    is_legend: bool = Field(
        True,
        description=(
            "Flag to indicate whether to display a legend. "
            "Set to True when multiple series or categories are plotted."
        ),
    )

    y_agg: Literal["sum", "mean", "count", "median", "min", "max", "none"] = Field(
        "none",
        description=(
            "Aggregation function applied to Y values when multiple records exist per X. "
            "Choose from: 'sum', 'mean', 'count', 'median', 'min', 'max', or 'none' for no aggregation."
        ),
    )

    title: str = Field(
        ...,
        description=(
            "Descriptive title for the chart summarizing what it represents. "
            "For example: 'Score by Attributes (2024)'."
        ),
    )

    # orientation: Literal["vertical", "horizontal", "none"] = Field(
    #     "vertical",
    #     description=(
    #         "Orientation of the chart. 'vertical' means standard X as category and Y as measure. "
    #         "'horizontal' swaps axes (useful for ranking or comparison charts). "
    #         "'none' when not applicable (like pie charts)."
    #     )
    # )

    sort: Literal["asc", "desc", "none"] = Field(
        "none",
        description=(
            "Sorting order for X-axis values based on Y metric. "
            "'asc' for ascending, 'desc' for descending, or 'none' to keep natural data order."
        ),
    )

    secondary_y: List[str] = Field(
        default_factory=list,
        description=(
            "ONLY for chart_type='combo'. The measure column(s) drawn as a LINE on "
            "a SECONDARY (right-hand) axis — typically a rate/percentage (e.g. "
            "'Growth_%', 'Share_of_Wallet'), while the columns in 'y' are drawn as "
            "BARS on the primary axis (typically an absolute amount like Premium). "
            "Use the EXACT column names from sql_output. Empty for all other charts."
        ),
    )

    waterfall_measures: List[str] = Field(
        default_factory=list,
        description=(
            "ONLY for chart_type='waterfall'. Optional per-step markers, one entry "
            "per X category in order, each either 'relative' (a +/- movement) or "
            "'total' (an absolute subtotal/total bar). Leave empty to treat every "
            "step as 'relative'; the engine then appends a final 'total' bar."
        ),
    )


class SurveyChartSignature(dspy.Signature):
    """
    [ROLE]
    You are an Expert Data Visualization Analyst specialized in interpreting survey data within the insurance domain.
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


class SurveyResponseSignature(dspy.Signature):
    """
    ROLE:
    You are a SENIOR INSURANCE CONSULTING LEADER (20+ years, McKinsey/Bain calibre) working as a strategic partner to a carrier's leadership team.
    You translate carrier SURVEY DATA (broker perception, NPS, satisfaction, category scores, peer benchmarks) into an executive-ready, insight-driven narrative.

    OBJECTIVE:
    Do NOT narrate the data. INTERPRET it. Every response must read like a partner briefing — findings, "so what", and clear next moves.
    Ground every statement in the provided sql_output. If a number is not in the data, do NOT invent it. If data is missing / empty, say so and move on.

    HARD OUTPUT CONTRACT — return a single Markdown string with these 5 sections in this exact order, using these exact headings:

    ### 📌 Executive Summary
    2-3 punchy lines. State the direct answer and the business impact (growth / risk / opportunity). Lead with the number that matters.

    ### 💡 Key Insights
    3-5 bullets. Each bullet MUST be an insight, not a restatement. Patterns, ranks, outliers, deltas, peer gaps, YoY shifts. Use icons 📈 📉 ⚠️ ✅ where natural. Bold the critical numbers.

    ### 🔍 Business Interpretation
    A short paragraph on WHY this is happening in the real insurance context — broker behaviour, service quality, claims experience, pricing perception, relationship strength, competitive positioning. Call out disconnects (e.g. strong premium but weak perception).

    ### 🎯 Recommendations
    2-4 specific, actionable bullets. Each bullet should start with a verb (Prioritise, Re-engage, Reposition, Audit, Invest). Tie back to the insight it addresses.

    ### 📊 Supporting Data
    Render the key numbers that back the story as a compact Markdown table (top 5-10 rows max). If the result is a single scalar, state it in one line.

    NARRATIVE ARC — the answer is a story, not a report (funnel: wide → narrow):
    - Sequence Key Insights as a funnel a leader can follow: start at the broadest
      level (overall NPS / total relationship standing), then narrow to the section,
      attribute, or segment driving it, and end with the sharpest, most specific
      finding (the outlier score, gap, or perception risk worth acting on).
    - Each section answers the question the previous one raises: the Summary states
      WHAT happened, Key Insights show WHERE it is concentrated, the Interpretation
      explains WHY, the Recommendations say WHAT TO DO about it.
    - Connect the dots explicitly ("that dip traces to…", "which is why…"). Never
      present disconnected bullets.

    STYLE RULES:
    - Executive tone. No hedging ("might", "could perhaps"). No filler ("it is worth noting that").
    - NEVER expose individual peer names — peers are always aggregated.
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
    response: str = dspy.OutputField(
        desc="Consulting-grade Markdown response with the 5 mandatory sections (Executive Summary, Key Insights, Business Interpretation, Recommendations, Supporting Data)."
    )
