"""
classification/subcategory_classifier.py

Stage 9 — Sub-category Classification.

Only runs when an umbrella classifier returns value=True.
Assigns the single most appropriate sub-category using the formal
sub-category definitions from taxonomy_definitions.py.

Returns null (sub_category=None) if the evidence does not clearly
support any sub-category — the system never forces a classification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Optional

from recap.schemas.enrichment import EnrichedInsight
from recap.schemas.classification import (
    ClassificationResult,
    SubCategoryResult,
    UmbrellaLabel,
)
from recap.llm.llm_client import LLMClient
from recap.taxonomy.taxonomy_definitions import (
    UMBRELLA_DEFINITIONS,
    get_sub_category_block,
)
from recap.prompts.prompts import (
    SUBCATEGORY_CLASSIFIER_SYSTEM_PROMPT,
    SUBCATEGORY_CLASSIFIER_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


class SubCategoryClassifier:
    """
    Classifies an insight into a sub-category for each active umbrella.

    Usage
    -----
    classifier = SubCategoryClassifier(llm_client)

    # umbrella_results: dict[umbrella_key, ClassificationResult]
    sub_results = await classifier.classify(insight, umbrella_results)
    # Returns: dict[umbrella_key, SubCategoryResult]
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self._llm = llm_client or LLMClient()

    async def classify(
        self,
        insight: EnrichedInsight,
        umbrella_results: Dict[str, ClassificationResult],
    ) -> Dict[str, SubCategoryResult]:
        """
        For each umbrella where value=True, run a sub-category classifier.
        All active sub-category classifiers run concurrently.

        Returns a dict mapping umbrella_key → SubCategoryResult.
        Only keys where umbrella value=True are included.
        """
        active_keys = [
            key for key, result in umbrella_results.items()
            if result.value
        ]

        if not active_keys:
            return {}

        tasks = {
            key: self._classify_one(insight, key)
            for key in active_keys
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        output: Dict[str, SubCategoryResult] = {}
        for key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning(
                    "Sub-category classification failed for %s / %s: %s",
                    insight.content_unit_id, key, result,
                )
                output[key] = SubCategoryResult(
                    umbrella=UmbrellaLabel(key),
                    sub_category=None,
                    confidence=0.0,
                    rationale=f"error: {result}",
                )
            else:
                output[key] = result

        return output

    async def _classify_one(
        self,
        insight: EnrichedInsight,
        umbrella_key: str,
    ) -> SubCategoryResult:
        umbrella_label = UMBRELLA_DEFINITIONS[umbrella_key]["label"]
        sub_category_block = get_sub_category_block(umbrella_key)

        system_prompt = SUBCATEGORY_CLASSIFIER_SYSTEM_PROMPT.format(
            umbrella_label=umbrella_label,
            sub_category_block=sub_category_block,
        )
        user_message = SUBCATEGORY_CLASSIFIER_USER_TEMPLATE.format(
            content_unit_id=insight.content_unit_id,
            content=insight.content,
        )

        try:
            raw = await self._llm.call(
                system_prompt=system_prompt,
                user_message=user_message,
                max_completion_tokens=256,
            )
            d = json.loads(raw) if isinstance(raw, str) else raw

            sub_cat_raw = d.get("sub_category")
            sub_cat = None
            if sub_cat_raw and sub_cat_raw not in ("null", "unknown", ""):
                # Validate against known sub-categories
                valid_keys = set(
                    UMBRELLA_DEFINITIONS[umbrella_key]["sub_categories"].keys()
                )
                sub_cat = sub_cat_raw if sub_cat_raw in valid_keys else None
                if sub_cat_raw and sub_cat is None:
                    logger.debug(
                        "LLM returned unknown sub-category %r for umbrella %s — setting null",
                        sub_cat_raw,
                        umbrella_key,
                    )

            # LLM sometimes returns integers [1, 2, 3] — coerce to strings
            raw_ids = d.get("evidence_element_ids", []) or []
            evidence_ids = [str(i) for i in raw_ids]

            return SubCategoryResult(
                umbrella=UmbrellaLabel(umbrella_key),
                sub_category=sub_cat,
                confidence=float(d.get("confidence", 0.0)),
                evidence_element_ids=evidence_ids,
                rationale=d.get("rationale"),
            )
        except Exception as exc:
            logger.warning(
                "Sub-category LLM call failed for %s / %s: %s",
                insight.content_unit_id, umbrella_key, exc,
            )
            return SubCategoryResult(
                umbrella=UmbrellaLabel(umbrella_key),
                sub_category=None,
                confidence=0.0,
                rationale=f"llm_error: {exc}",
            )
