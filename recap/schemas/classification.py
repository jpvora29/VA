"""
schemas/classification.py

Structured outputs for the four independent umbrella classifiers
and the sub-category classifier.

Each umbrella is a Boolean with confidence and evidence.
A single insight can belong to multiple umbrellas (multi-label).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Umbrella taxonomy labels
# ---------------------------------------------------------------------------

class UmbrellaLabel(str, Enum):
    PERFORMANCE_AND_POSITION   = "performance_and_position"
    OPPORTUNITY_AND_GROWTH     = "opportunity_and_growth"
    MARKET_AND_EXTERNAL_CONTEXT = "market_and_external_context"
    RELATIONSHIP_AND_COLLABORATION = "relationship_and_collaboration"


# ---------------------------------------------------------------------------
# Sub-category labels per umbrella
# (populated from taxonomy_definitions.py at runtime)
# ---------------------------------------------------------------------------

class PerformanceSubCategory(str, Enum):
    FINANCIAL_PERFORMANCE = "financial_performance"
    OPERATIONAL_PERFORMANCE = "operational_performance"
    MARKET_POSITION       = "market_position"
    CLIENT_PERFORMANCE    = "client_performance"
    OTHER                 = "other"


class GrowthSubCategory(str, Enum):
    REVENUE_GROWTH        = "revenue_growth"
    NEW_BUSINESS          = "new_business"
    STRATEGIC_OPPORTUNITY = "strategic_opportunity"
    PIPELINE              = "pipeline"
    OTHER                 = "other"


class MarketSubCategory(str, Enum):
    MACRO_ECONOMIC        = "macro_economic"
    REGULATORY            = "regulatory"
    COMPETITIVE_LANDSCAPE = "competitive_landscape"
    INDUSTRY_TRENDS       = "industry_trends"
    OTHER                 = "other"


class RelationshipSubCategory(str, Enum):
    PARTNERSHIP           = "partnership"
    CLIENT_ENGAGEMENT     = "client_engagement"
    GOVERNANCE            = "governance"
    STAKEHOLDER_UPDATE    = "stakeholder_update"
    OTHER                 = "other"


# ---------------------------------------------------------------------------
# Single umbrella classification result
# ---------------------------------------------------------------------------

class ClassificationResult(BaseModel):
    """
    Output of one Boolean umbrella classifier.
    """
    umbrella: UmbrellaLabel
    value: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_element_ids: List[str] = Field(default_factory=list)
    rationale: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-category result (only produced when umbrella value=True)
# ---------------------------------------------------------------------------

class SubCategoryResult(BaseModel):
    umbrella: UmbrellaLabel
    sub_category: Optional[str] = Field(
        default=None,
        description=(
            "Sub-category label from the relevant enum, or null if "
            "insufficient evidence."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence_element_ids: List[str] = Field(default_factory=list)
    rationale: Optional[str] = None


# ---------------------------------------------------------------------------
# Complete classification bundle for one insight
# ---------------------------------------------------------------------------

class ClassificationBundle(BaseModel):
    """
    All umbrella + sub-category results for a single EnrichedInsight.
    """
    content_unit_id: str

    performance_and_position: ClassificationResult
    opportunity_and_growth: ClassificationResult
    market_and_external_context: ClassificationResult
    relationship_and_collaboration: ClassificationResult

    # Sub-categories — only set when corresponding umbrella value=True
    performance_sub_category: Optional[SubCategoryResult]      = None
    growth_sub_category: Optional[SubCategoryResult]           = None
    market_sub_category: Optional[SubCategoryResult]           = None
    relationship_sub_category: Optional[SubCategoryResult]     = None

    def active_umbrellas(self) -> List[UmbrellaLabel]:
        """Returns list of umbrella labels where value=True.

        Hard cap: at most 3 umbrellas per insight.  If the LLM returns
        more than 3 trues, keep only the highest-confidence ones so that
        over-eager multi-labelling is silently corrected at the schema level.
        """
        results = [
            self.performance_and_position,
            self.opportunity_and_growth,
            self.market_and_external_context,
            self.relationship_and_collaboration,
        ]
        active = [r for r in results if r.value]
        if len(active) > 3:
            # Sort descending by confidence, keep top 3
            active = sorted(active, key=lambda r: r.confidence, reverse=True)[:3]
        return [r.umbrella for r in active]
