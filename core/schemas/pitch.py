"""Pydantic models for the pitch builder structured-output calls.

These are used directly with `llm.with_structured_output(...)` rather than
through dspy; the pitch flow does not currently use dspy signatures.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PitchMetricEvidence(BaseModel):
    metric: str = Field(
        description="Metric or measure name exactly as supported by the evidence."
    )
    value: str = Field(
        description="Metric value as text, preserving formatting from the evidence."
    )
    context: str = Field(
        default="",
        description="Optional product, segment, carrier, region, period, or other qualifier.",
    )


class PitchEvidenceRow(BaseModel):
    row_summary: str = Field(
        description="Concise text summary of the relevant SQL row."
    )
    source: str = Field(
        default="", description="Optional source table, query, or column context."
    )


class PitchExtractedInsight(BaseModel):
    question: str = Field(description="Original pitch-builder question.")
    answer_summary: str = Field(
        description="Short factual answer summary grounded in SQL evidence."
    )
    route: str = Field(
        description="Route used to answer the question: survey, premium, both, fallback, or error."
    )
    extracted_metrics: list[PitchMetricEvidence] = Field(
        default_factory=list,
        description=(
            "Metric-agnostic dictionary of all directly support measures. "
            "Keys should follow the user's/business wording or SQL column names, and values can be strings, numbers, list, or nested dictionaries."
        ),
    )
    business_meaning: str = Field(
        default="",
        description="Plain-language business meaning for junior insurance leaders.",
    )
    evidence_rows_used: list[PitchEvidenceRow] = Field(
        default_factory=list, description="Small list of SQL rows used as evidence. "
    )
    confidence: str = Field(
        default="medium",
        description="high, medium, or low based on completness of evidence.",
    )
    limitations: list[str] = Field(
        default_factory=list, description="Evidence gaps or extraction warnings."
    )


class PitchTopKPIs(BaseModel):
    total_curr_premium: str = Field(
        default="",
        description="Carrier-only total current year premium, formatted as in the evidence (e.g. '$12.3M'). Empty if not supported.",
    )
    yoy: str = Field(
        default="",
        description="Carrier-only YoY growth percentage as text (e.g. '8.4%'). Empty if not supported.",
    )
    gpr_rank: str = Field(
        default="",
        description="Carrier rank as text (e.g. '3' or '#3'). Empty if not supported.",
    )
    rank_delta: str = Field(
        default="",
        description="Change in the carrier rank vs prior period as signed text (e.g. '-1', '+2'). Calculate it as rank - last_year_rank. Empty if not supported.",
    )
    survey_score: str = Field(
        default="",
        description="Carrier survey score (overall) as text. Empty if not supported.",
    )
    policies: str = Field(
        default="", description="Carrier policy count as text. Empty if not supported."
    )
    last_year_rank: str = Field(
        default="",
        description="Carrier rank for the prior year as text. Empty if not suported.",
    )
