"""
store/insight_store.py

Stage 13 — Structured Insight Store.

Assembles and persists StructuredInsight records after all classification
stages complete. Supports:
  - In-memory storage (default, for pipeline use)
  - JSON file persistence (for auditing and cross-session recall)
  - Flexible filtering / querying by any business dimension

Provenance chain preserved in every record:
  StructuredInsight → SCU → RawElement(s) → RawSlide → RawDeck
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from recap.schemas.action_item import ActionItemResult
from recap.schemas.classification import (
    ClassificationBundle,
    ClassificationResult,
    SubCategoryResult,
    UmbrellaLabel,
)
from recap.schemas.enrichment import EnrichedInsight, Urgency
from recap.schemas.insight_store import StructuredInsight
from recap.schemas.raw_extraction import RawDeck

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Assembly helper
# ---------------------------------------------------------------------------

def assemble_insight(
    enriched: EnrichedInsight,
    umbrella_results: Dict[str, ClassificationResult],
    sub_category_results: Dict[str, SubCategoryResult],
    action_item_result: ActionItemResult,
    deck: RawDeck,
) -> StructuredInsight:
    """
    Combine all stage outputs into a single StructuredInsight record.

    Parameters
    ----------
    enriched              : Output of the enrichment LLM.
    umbrella_results      : dict[umbrella_key, ClassificationResult]
    sub_category_results  : dict[umbrella_key, SubCategoryResult]
    action_item_result    : Output of the action-item classifier.
    deck                  : The source RawDeck (for meeting/client metadata).
    """
    # Build ClassificationBundle
    def _umbrella(key: str) -> ClassificationResult:
        return umbrella_results.get(
            key,
            ClassificationResult(
                umbrella=UmbrellaLabel(key),
                value=False,
                confidence=0.0,
            ),
        )

    def _sub(key: str) -> Optional[SubCategoryResult]:
        return sub_category_results.get(key)

    bundle = ClassificationBundle(
        content_unit_id=enriched.content_unit_id,
        performance_and_position=_umbrella("performance_and_position"),
        opportunity_and_growth=_umbrella("opportunity_and_growth"),
        market_and_external_context=_umbrella("market_and_external_context"),
        relationship_and_collaboration=_umbrella("relationship_and_collaboration"),
        performance_sub_category=_sub("performance_and_position"),
        growth_sub_category=_sub("opportunity_and_growth"),
        market_sub_category=_sub("market_and_external_context"),
        relationship_sub_category=_sub("relationship_and_collaboration"),
    )

    insight_id = f"INS_{enriched.deck_id}_{enriched.content_unit_id}"

    insight = StructuredInsight(
        insight_id=insight_id,
        content_unit_id=enriched.content_unit_id,
        deck_id=enriched.deck_id,
        slide_number=enriched.slide_number,
        section=enriched.section,
        slide_title=enriched.slide_title,
        meeting_date=deck.meeting_date,
        quarter=deck.quarter,
        half_year=deck.half_year,
        year=deck.year,
        period_label=deck.period_label,
        client_name=deck.client_name,
        company_name=deck.company_name,
        content=enriched.content,
        source_element_ids=enriched.source_element_ids,
        metadata=enriched.metadata,
        classification=bundle,
        action_item=action_item_result,
        glossary_terms_used=enriched.glossary_terms_used,
    )
    insight.populate_flat_fields()
    return insight


# ---------------------------------------------------------------------------
# Insight Store
# ---------------------------------------------------------------------------

class InsightStore:
    """
    In-memory store for StructuredInsight records with optional JSON
    persistence and flexible multi-field querying.

    Usage
    -----
    store = InsightStore()
    store.add(insight)
    store.save("outputs/insights.json")

    results = store.query(
        deck_id="client_q2_2026",
        umbrella="performance_and_position",
        performance_direction="positive",
        is_action_item=True,
    )
    """

    def __init__(self) -> None:
        self._insights: List[StructuredInsight] = []
        self._index: Dict[str, StructuredInsight] = {}   # insight_id → insight

    # ----------------------------------------------------------------
    # Write
    # ----------------------------------------------------------------

    def add(self, insight: StructuredInsight) -> None:
        """Add a single insight to the store."""
        self._insights.append(insight)
        self._index[insight.insight_id] = insight

    def add_many(self, insights: List[StructuredInsight]) -> None:
        """Add multiple insights."""
        for ins in insights:
            self.add(ins)

    # ----------------------------------------------------------------
    # Read
    # ----------------------------------------------------------------

    def get(self, insight_id: str) -> Optional[StructuredInsight]:
        """Retrieve a single insight by ID."""
        return self._index.get(insight_id)

    def all(self) -> List[StructuredInsight]:
        """Return all stored insights."""
        return list(self._insights)

    @property
    def count(self) -> int:
        return len(self._insights)

    # ----------------------------------------------------------------
    # Query
    # ----------------------------------------------------------------

    def query(
        self,
        *,
        deck_id: Optional[str] = None,
        client_name: Optional[str] = None,
        quarter: Optional[str] = None,
        year: Optional[int] = None,
        period_label: Optional[str] = None,
        section: Optional[str] = None,
        umbrella: Optional[str] = None,
        sub_category: Optional[str] = None,
        lob: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        kpi: Optional[str] = None,
        performance_direction: Optional[str] = None,
        is_action_item: Optional[bool] = None,
        urgency: Optional[str] = None,
        min_confidence: Optional[float] = None,
    ) -> List[StructuredInsight]:
        """
        Filter insights by any combination of fields.
        All filters are ANDed together; omitted filters are ignored.
        String comparisons are case-insensitive.
        """
        results = self._insights

        if deck_id is not None:
            results = [r for r in results if r.deck_id == deck_id]

        if client_name is not None:
            results = [
                r for r in results
                if r.client_name and r.client_name.lower() == client_name.lower()
            ]

        if quarter is not None:
            results = [r for r in results if r.quarter == quarter]

        if year is not None:
            results = [r for r in results if r.year == year]

        if period_label is not None:
            results = [
                r for r in results
                if r.period_label and period_label.lower() in r.period_label.lower()
            ]

        if section is not None:
            results = [
                r for r in results
                if r.section and section.lower() in r.section.lower()
            ]

        if umbrella is not None:
            results = [r for r in results if umbrella in r.umbrella_labels]

        if sub_category is not None:
            results = [r for r in results if sub_category in r.sub_category_labels]

        if lob is not None:
            results = [
                r for r in results
                if any(lob.lower() in l.lower() for l in r.metadata.lines_of_business)
            ]

        if country is not None:
            results = [
                r for r in results
                if any(country.lower() in c.lower() for c in r.metadata.countries)
            ]

        if region is not None:
            results = [
                r for r in results
                if any(region.lower() in reg.lower() for reg in r.metadata.regions)
            ]

        if kpi is not None:
            results = [
                r for r in results
                if any(kpi.lower() in k.lower() for k in r.metadata.kpis)
            ]

        if performance_direction is not None:
            results = [
                r for r in results
                if r.metadata.performance_direction.value == performance_direction
            ]

        if is_action_item is not None:
            results = [
                r for r in results
                if r.action_item.is_action_item == is_action_item
            ]

        if urgency is not None:
            results = [
                r for r in results
                if r.action_item.urgency.value == urgency
            ]

        if min_confidence is not None:
            results = [
                r for r in results
                if r.metadata.overall_confidence >= min_confidence
            ]

        return results

    def get_action_items(
        self, urgency: Optional[str] = None
    ) -> List[StructuredInsight]:
        """Return all action items, optionally filtered by urgency."""
        return self.query(is_action_item=True, urgency=urgency)

    def get_by_umbrella(self, umbrella_key: str) -> List[StructuredInsight]:
        """Return all insights belonging to a given umbrella."""
        return self.query(umbrella=umbrella_key)

    # ----------------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """
        Persist all insights to a JSON file.
        Creates parent directories automatically.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [ins.model_dump(mode="json") for ins in self._insights]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("InsightStore saved: %d insights → %s", len(data), path)

    @classmethod
    def load(cls, path: str | Path) -> "InsightStore":
        """
        Load insights from a previously saved JSON file.
        Returns an empty store if the file does not exist.
        """
        path = Path(path)
        store = cls()
        if not path.exists():
            logger.warning("InsightStore file not found: %s", path)
            return store
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for record in data:
            try:
                insight = StructuredInsight.model_validate(record)
                store.add(insight)
            except Exception as exc:
                logger.warning("Skipping malformed insight record: %s", exc)
        logger.info("InsightStore loaded: %d insights ← %s", store.count, path)
        return store

    # ----------------------------------------------------------------
    # Provenance trace
    # ----------------------------------------------------------------

    def trace(self, insight_id: str) -> Dict[str, Any]:
        """
        Return the full provenance trace for a single insight.
        Useful for explaining why a takeaway was included in a recap.
        """
        insight = self.get(insight_id)
        if insight is None:
            return {"error": f"Insight {insight_id!r} not found"}

        active_umbrellas = insight.umbrella_labels
        sub_cats = {
            k: (v.sub_category if v else None)
            for k, v in [
                ("performance_and_position",      insight.classification.performance_sub_category),
                ("opportunity_and_growth",         insight.classification.growth_sub_category),
                ("market_and_external_context",    insight.classification.market_sub_category),
                ("relationship_and_collaboration", insight.classification.relationship_sub_category),
            ]
        }

        return {
            "insight_id":           insight.insight_id,
            "content":              insight.content,
            "deck_id":              insight.deck_id,
            "slide_number":         insight.slide_number,
            "slide_title":          insight.slide_title,
            "section":              insight.section,
            "source_element_ids":   insight.source_element_ids,
            "content_unit_id":      insight.content_unit_id,
            "glossary_terms_used":  insight.glossary_terms_used,
            "metadata":             insight.metadata.model_dump(),
            "active_umbrellas":     active_umbrellas,
            "sub_categories":       sub_cats,
            "action_item": {
                "is_action_item":   insight.action_item.is_action_item,
                "urgency":          insight.action_item.urgency.value,
                "action":           insight.action_item.action_description,
                "owner":            insight.action_item.owner,
                "deadline":         insight.action_item.deadline,
                "confidence":       insight.action_item.confidence,
            },
            "overall_confidence":   insight.metadata.overall_confidence,
        }
