"""
schemas/insight_store.py

StructuredInsight is the fully assembled record that is persisted
in the Insight Store after all classification stages are complete.

It carries:
  - identity / source provenance
  - raw content
  - enriched metadata
  - full classification bundle
  - action-item result

This record is the input to the Recap Generator.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .enrichment import InsightMetadata
from .classification import ClassificationBundle
from .action_item import ActionItemResult


class StructuredInsight(BaseModel):
    """
    Complete, queryable record for one business insight.

    Provenance chain:
        StructuredInsight
          → content_unit_id  → SemanticContentUnit
          → source_element_ids → RawElement(s)
          → slide_number      → RawSlide
          → deck_id           → RawDeck (original file)
    """

    # --- Identity ---
    insight_id: str = Field(
        description="Unique ID for this insight, e.g. 'INS_client_q2_2026_CU_012_04'."
    )
    content_unit_id: str
    deck_id: str
    slide_number: int
    section: Optional[str]     = None
    slide_title: Optional[str] = None

    # --- Deck / meeting context ---
    meeting_date: Optional[str]   = None
    quarter: Optional[str]        = None
    half_year: Optional[str]      = None
    year: Optional[int]           = None
    period_label: Optional[str]   = None
    client_name: Optional[str]    = None
    company_name: Optional[str]   = None

    # --- Content ---
    content: str
    source_element_ids: List[str] = Field(min_length=1)

    # --- Enriched metadata ---
    metadata: InsightMetadata

    # --- Taxonomy classification ---
    classification: ClassificationBundle

    # --- Action item ---
    action_item: ActionItemResult

    # --- Glossary terms used during processing ---
    glossary_terms_used: List[str] = Field(default_factory=list)

    # --- Query-friendly flat fields (denormalised for fast filtering) ---
    umbrella_labels: List[str]    = Field(default_factory=list)
    sub_category_labels: List[str] = Field(default_factory=list)

    def populate_flat_fields(self) -> None:
        """
        Populate denormalised umbrella_labels and sub_category_labels
        from the classification bundle. Call after assembly.

        Parent–child enforcement: a sub-category is only included in
        sub_category_labels when its parent umbrella survived the
        active_umbrellas() cull and is present in umbrella_labels.
        This prevents orphaned sub-category labels (e.g. market_conditions
        appearing without market_and_external_context in umbrella_labels).
        """
        self.umbrella_labels = [
            u.value for u in self.classification.active_umbrellas()
        ]
        active_umbrella_set = set(self.umbrella_labels)

        # Map each sub-category slot to its parent umbrella key
        sub_cat_slots = [
            ("performance_and_position",      self.classification.performance_sub_category),
            ("opportunity_and_growth",         self.classification.growth_sub_category),
            ("market_and_external_context",    self.classification.market_sub_category),
            ("relationship_and_collaboration", self.classification.relationship_sub_category),
        ]

        sub_cats: List[str] = []
        for parent_umbrella_key, sc in sub_cat_slots:
            if sc and sc.sub_category:
                # Only include if the parent umbrella is still active
                if parent_umbrella_key in active_umbrella_set:
                    sub_cats.append(sc.sub_category)

        self.sub_category_labels = sub_cats
