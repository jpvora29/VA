"""
schemas/recap.py

Structured output schema for the Recap Generator.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .enrichment import Urgency


class ActionItemSummary(BaseModel):
    """A single action item in the recap."""
    action: str
    owner: Optional[str]       = None
    deadline: Optional[str]    = None
    line_of_business: Optional[str] = None
    geography: Optional[str]   = None
    urgency: Urgency            = Urgency.UNKNOWN
    source_slide_number: Optional[int] = None
    source_content_unit_id: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    # Composite ranking score (higher = more important); computed at parse time
    priority_score: float = Field(default=0.0, exclude=True)


class TitledTakeaway(BaseModel):
    """
    A single key takeaway bullet with a short title and a narrative sentence.

    Format on the slide:
      • <title>: <narrative>

    Example:
      • Country Priorities: Germany remains the anchor market, Spain is
        outperforming plan, and the Netherlands shows the strongest growth.
    """
    title: str = Field(description="Short label (2–5 words) identifying the topic.")
    narrative: str = Field(
        description=(
            "One rich sentence synthesising the key insight(s) for this topic. "
            "Should be substantive and specific — no vague generalities."
        )
    )
    umbrella: str = Field(description="Source umbrella category key.")
    sub_category: Optional[str] = Field(
        default=None,
        description="Source sub-category key, or null if umbrella-level only.",
    )
    source_content_unit_ids: List[str] = Field(default_factory=list)


class CountrySummary(BaseModel):
    """
    A two-sentence summary of all insights tagged with a specific country.

    Rendered on Slide 2 as:
      <Country name (bold, amber)>: summary text
    """
    country: str = Field(description="Country name exactly as extracted.")
    summary: str = Field(
        description=(
            "Two concise sentences summarising the key commercial insights "
            "for this country. Specific — name LOBs, directions, actions."
        )
    )
    source_content_unit_ids: List[str] = Field(default_factory=list)


class RecapOutput(BaseModel):
    """
    The final structured recap that will be rendered on the
    'Next Meeting Recap' slide.
    """

    deck_id: str
    period_label: Optional[str]   = None
    client_name: Optional[str]    = None

    # One-line executive summary
    executive_summary: str

    # Key takeaways — flat list of titled bullets, one per (umbrella, sub_category) group
    key_takeaways: List[TitledTakeaway] = Field(default_factory=list)

    # Top 3–4 prioritised action items (ranked by urgency + impact)
    action_items: List[ActionItemSummary] = Field(default_factory=list)

    # Per-country summaries — only populated when 2+ unique countries are present
    country_summaries: List[CountrySummary] = Field(default_factory=list)

    # Overall confidence in the recap (mean of contributing insights)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)

    # IDs of all insights that contributed to this recap
    contributing_insight_ids: List[str] = Field(default_factory=list)
