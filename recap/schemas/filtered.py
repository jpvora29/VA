"""
schemas/filtered.py

Represents the outcome of the noise-filtering stage.
The raw extraction is never modified — filtering is a separate overlay.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class FilterReason(str, Enum):
    """Why an element was flagged as noise."""
    PAGE_NUMBER          = "page_number"
    SLIDE_NUMBER         = "slide_number"
    FOOTER_CLIENT_NAME   = "footer_client_name"
    FOOTER_COMPANY_NAME  = "footer_company_name"
    COPYRIGHT_NOTICE     = "copyright_notice"
    CONFIDENTIALITY      = "confidentiality"
    LEGAL_DISCLAIMER     = "legal_disclaimer"
    TEMPLATE_BOILERPLATE = "template_boilerplate"
    NAVIGATION_ELEMENT   = "navigation_element"
    DECORATIVE_TEXT      = "decorative_text"
    EMPTY_SHAPE          = "empty_shape"
    DECORATIVE_SHAPE     = "decorative_shape"
    LOGO                 = "logo"
    LLM_AMBIGUOUS        = "llm_ambiguous"    # resolved by LLM pass
    RETAINED             = "retained"         # explicitly kept (not noise)


class FilterDecision(BaseModel):
    """
    Immutable record of why an element was kept or removed.
    Both keep and remove decisions are recorded for auditability.
    """
    element_id: str
    is_noise: bool

    reason: FilterReason = FilterReason.RETAINED
    rule_triggered: Optional[str] = Field(
        default=None,
        description="Name of the rule that triggered this decision, if rule-based.",
    )
    llm_used: bool = False
    llm_rationale: Optional[str] = Field(
        default=None,
        description="LLM explanation when llm_used=True.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence that this is the correct filter decision.",
    )


class FilteredElement(BaseModel):
    """
    Wraps a RawElement with its filter decision.
    Downstream stages only consume elements where is_noise=False.
    """
    element_id: str
    deck_id: str
    slide_number: int
    decision: FilterDecision

    @property
    def is_noise(self) -> bool:
        return self.decision.is_noise


class FilteredSlide(BaseModel):
    """All filter decisions for a single slide."""
    deck_id: str
    slide_number: int
    decisions: List[FilterDecision] = Field(default_factory=list)

    def kept_element_ids(self) -> List[str]:
        return [d.element_id for d in self.decisions if not d.is_noise]

    def removed_element_ids(self) -> List[str]:
        return [d.element_id for d in self.decisions if d.is_noise]
