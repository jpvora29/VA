"""Schemas for the inline Boardroom dashboard digest.

When Boardroom Mode is active for a turn, `core.agents.boardroom.boardroom_node`
runs *after* the route's insight writer and distills the already-written
commentary + SQL rows into a structured `BoardroomDigest`: a handful of KPI
cards, a one-line headline, and grouped commentary points. The UI renders that
digest as a single inline dashboard card (KPIs on top, commentary rail on the
left, charts on the right) instead of plain markdown.

The digest is *presentation* metadata — it never re-runs analysis. It only
reshapes the numbers and narrative the deterministic/analyst rails already
produced, so it cannot contradict the underlying answer.
"""
from __future__ import annotations

from typing import List, Literal

import dspy
from pydantic import BaseModel, Field

Tone = Literal["good", "warn", "danger", "neutral"]


class KpiCard(BaseModel):
    """A single headline metric tile."""

    label: str = Field(description="Short metric name, e.g. 'Gross Premium' or 'GPR Rank'.")
    value: str = Field(
        description="The formatted headline value exactly as it should display, e.g. '$57.6M', '#14', '7.1'."
    )
    delta: str = Field(
        default="",
        description="Short change/context note, e.g. '-9.2% YoY', '+0.3 vs prior', 'near peer avg'. Empty when there is no comparison.",
    )
    tone: Tone = Field(
        default="neutral",
        description="Sentiment of the metric from the carrier's perspective: 'good' (favourable), 'warn' (caution), 'danger' (adverse), 'neutral'.",
    )
    icon: str = Field(
        default="bi bi-graph-up",
        description="A Bootstrap-icon class that fits the metric (e.g. 'bi bi-currency-dollar', 'bi bi-trophy', 'bi bi-stars', 'bi bi-pie-chart').",
    )


class CommentarySection(BaseModel):
    """A titled cluster of commentary bullet points for the left rail."""

    heading: str = Field(description="Short section heading, e.g. 'What changed' or 'Drivers'.")
    points: List[str] = Field(
        default_factory=list,
        description="2-4 concise, board-ready bullet points. Each is a full sentence, no markdown.",
    )


class RiskItem(BaseModel):
    """A single risk/watch item rendered as a labelled severity bar."""

    label: str = Field(description="Short risk name, e.g. 'Rank decline'.")
    severity: str = Field(description="One of 'High', 'Med', 'Low'.")
    tone: Tone = Field(default="warn", description="Bar colour tone matching the severity.")


class BoardroomDigest(BaseModel):
    """Structured dashboard view of a single answer."""

    title: str = Field(description="Dashboard title — usually the carrier or subject, e.g. 'Zurich — Canada'.")
    subtitle: str = Field(
        default="",
        description="One-line context, e.g. '2024 premium performance vs peer set'.",
    )
    headline: str = Field(
        default="",
        description="A single punchy sentence stating the bottom line of the answer.",
    )
    kpis: List[KpiCard] = Field(
        default_factory=list,
        description="3-5 KPI cards covering the most decision-relevant numbers in the answer.",
    )
    commentary: List[CommentarySection] = Field(
        default_factory=list,
        description="1-3 commentary sections distilled from the written analysis.",
    )
    risks: List[RiskItem] = Field(
        default_factory=list,
        description="0-4 risk/watch items if the analysis surfaces any; otherwise empty.",
    )


class BoardroomSignature(dspy.Signature):
    """
    [ROLE]
    You are an executive briefing designer. You receive an analyst's finished
    written answer (commentary) and the underlying result rows for an insurance
    carrier question, and you reshape them into a boardroom dashboard digest.

    [OBJECTIVE]
    Produce a `BoardroomDigest` that a C-suite reader could absorb in seconds:
    - 3-5 KPI cards with the most decision-relevant numbers, each formatted for
      display and tagged with the correct sentiment tone from the carrier's
      perspective (a premium decline is 'danger', a rank improvement is 'good').
    - A single-sentence `headline` stating the bottom line.
    - 1-3 commentary sections (heading + 2-4 crisp bullets) distilled from the
      written analysis.
    - 0-4 risk items only if the analysis genuinely surfaces risks.

    [HARD CONSTRAINTS]
    - Use ONLY numbers and facts present in the commentary or rows. Never invent,
      extrapolate, or round in a way that changes meaning. If a comparison is not
      stated, leave `delta` empty.
    - Keep every string short and board-ready. No markdown, no citations.
    - The digest must be faithful to the commentary; it reformats, never reanalyses.
    """

    user_query: str = dspy.InputField(desc="The user's original question.")
    route: str = dspy.InputField(desc="Which analytical lens produced the answer (survey/premium/both/analyst/fallback).")
    commentary: str = dspy.InputField(desc="The finished written analysis to distil.")
    sql_output: list = dspy.InputField(desc="Underlying result rows (may be a truncated sample).")
    digest: BoardroomDigest = dspy.OutputField(
        desc="Structured boardroom dashboard digest faithful to the commentary."
    )
