"""
schemas/enrichment.py

Structured output schema for the Metadata / Semantic Enrichment LLM.
Every field that the LLM populates is wrapped with a confidence score
and the evidence element IDs that support it.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

class PerformanceDirection(str, Enum):
    POSITIVE  = "positive"
    NEGATIVE  = "negative"
    NEUTRAL   = "neutral"
    MIXED     = "mixed"
    UNKNOWN   = "unknown"


class GrowthType(str, Enum):
    YOY   = "yoy"    # year-over-year
    QOQ   = "qoq"    # quarter-over-quarter
    HOH   = "hoh"    # half-over-half
    MTD   = "mtd"    # month-to-date
    YTD   = "ytd"    # year-to-date
    CAGR  = "cagr"
    OTHER = "other"
    UNKNOWN = "unknown"


class Urgency(str, Enum):
    HIGH    = "high"
    MEDIUM  = "medium"
    LOW     = "low"
    NONE    = "none"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Typed evidence wrapper — used on every LLM-generated field
# ---------------------------------------------------------------------------

class EvidenceField(BaseModel):
    """
    Wraps any LLM-generated value with a confidence score and
    the source element IDs that support the value.
    """
    value: Optional[object] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence_element_ids: List[str] = Field(default_factory=list)
    rationale: Optional[str] = None


# ---------------------------------------------------------------------------
# Metadata produced by the enrichment LLM
# ---------------------------------------------------------------------------

class InsightMetadata(BaseModel):
    """
    Business metadata extracted from a single SemanticContentUnit.
    All fields are optional; the LLM returns null/unknown when
    there is insufficient evidence.
    """

    # Organisational scope
    lines_of_business: List[str]  = Field(default_factory=list)
    countries: List[str]          = Field(default_factory=list)
    regions: List[str]            = Field(default_factory=list)
    segments: List[str]           = Field(default_factory=list)
    # Note: geographies removed — regions + countries together cover this concept

    # Metrics
    kpis: List[str]               = Field(default_factory=list)
    metrics: List[str]            = Field(default_factory=list)

    # Performance
    performance_direction: PerformanceDirection = PerformanceDirection.UNKNOWN
    growth_type: Optional[GrowthType]           = None
    growth_value: Optional[str]                 = None   # e.g. "+14%" or "2x"
    baseline_value: Optional[str]               = None   # e.g. "18%"
    current_value: Optional[str]                = None   # e.g. "23%"

    # Update type flags
    is_client_update: bool   = False
    is_company_update: bool  = False
    is_market_condition: bool = False
    is_opportunity: bool     = False
    is_concern: bool         = False

    # People / ownership
    owner: Optional[str] = None
    deadline: Optional[str] = None   # ISO-8601 or free-form as found in PPT

    # Glossary terms matched during enrichment
    matched_glossary_terms: List[str] = Field(default_factory=list)

    # Confidence on the overall metadata extraction
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class EnrichedInsight(BaseModel):
    """
    A SemanticContentUnit after metadata enrichment.
    Retains full provenance back to the SCU and its source elements.
    """

    # Identity — mirrors the originating SCU
    content_unit_id: str
    deck_id: str
    slide_number: int
    section: Optional[str]    = None
    slide_title: Optional[str] = None
    content: str

    # Source provenance
    source_element_ids: List[str] = Field(min_length=1)

    # Enriched metadata
    metadata: InsightMetadata

    # Glossary definitions that were injected into the LLM prompt
    glossary_terms_used: List[str] = Field(default_factory=list)
