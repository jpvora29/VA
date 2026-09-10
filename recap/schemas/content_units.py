"""
schemas/content_units.py

A SemanticContentUnit (SCU) groups one or more related RawElements
into a single meaningful business point.

Every SCU retains the IDs of all contributing elements so that
full provenance to the original PPT is always available.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ContentUnitType(str, Enum):
    KPI_CARD      = "kpi_card"
    CHART_INSIGHT = "chart_insight"
    TABLE_ROW     = "table_row"
    TABLE_BLOCK   = "table_block"
    BULLET_POINT  = "bullet_point"
    PARAGRAPH     = "paragraph"
    NARRATIVE     = "narrative"
    ACTION_ITEM   = "action_item"
    MIXED         = "mixed"
    UNKNOWN       = "unknown"


class GroupingMethod(str, Enum):
    SPATIAL_PROXIMITY  = "spatial_proximity"
    PPTX_GROUP         = "pptx_group"
    CHART_ELEMENTS     = "chart_elements"
    TABLE_ELEMENTS     = "table_elements"
    READING_ORDER      = "reading_order"
    SLIDE_NOTES        = "slide_notes"
    MANUAL             = "manual"


class SemanticContentUnit(BaseModel):
    """
    A semantically coherent business point derived from one or more
    raw PPT elements.

    Key invariant: source_element_ids always contains ≥1 element_id
    from the corresponding RawSlide, preserving full provenance.
    """

    content_unit_id: str = Field(
        description="Unique ID, e.g. 'CU_slide03_004'."
    )
    deck_id: str
    slide_number: int
    section: Optional[str] = None
    slide_title: Optional[str] = None

    # --- Content ---
    content: str = Field(
        description="Human-readable text of the business point."
    )
    content_unit_type: ContentUnitType = ContentUnitType.UNKNOWN

    # --- Provenance ---
    source_element_ids: List[str] = Field(
        min_length=1,
        description="IDs of all RawElements that contributed to this SCU.",
    )
    grouping_method: GroupingMethod = GroupingMethod.SPATIAL_PROXIMITY

    # --- Spatial context (bounding box of the group, EMU) ---
    bounding_x: Optional[int]      = None
    bounding_y: Optional[int]      = None
    bounding_width: Optional[int]  = None
    bounding_height: Optional[int] = None

    # --- Reading position within slide ---
    reading_order: Optional[int]   = None   # ordering among SCUs on this slide

    # --- Formatting hints useful for enrichment ---
    has_numeric_value: bool = False
    has_percentage: bool    = False
    has_currency: bool      = False
    has_trend_indicator: bool = False   # ▲ ▼ + - arrow glyphs
