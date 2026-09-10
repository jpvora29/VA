"""
schemas/action_item.py

Structured output for the action-item classifier.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .enrichment import Urgency


class ActionItemResult(BaseModel):
    """
    Determines whether a SemanticContentUnit contains an action item
    and, if so, characterises its urgency and supporting evidence.
    """

    content_unit_id: str

    is_action_item: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_element_ids: List[str] = Field(default_factory=list)
    rationale: Optional[str] = None

    # Only populated when is_action_item=True
    urgency: Urgency = Urgency.UNKNOWN
    urgency_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    urgency_rationale: Optional[str] = None

    # Structured action details — extracted when is_action_item=True
    action_description: Optional[str] = None
    owner: Optional[str]              = None
    deadline: Optional[str]           = None   # ISO-8601 or free-form
    line_of_business: Optional[str]   = None
    geography: Optional[str]          = None

    # Source context
    source_slide_number: Optional[int] = None
    source_section: Optional[str]      = None
