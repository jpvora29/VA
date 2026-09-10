"""
classification/umbrella_classifiers.py

Stages 7–8 — Four independent Boolean umbrella classifiers.

Each classifier decides whether an EnrichedInsight belongs to its
umbrella category. They run CONCURRENTLY per insight (4 parallel calls).

Classification is multi-label: a single insight can belong to multiple
umbrellas simultaneously. Each classifier is independent.

Every classifier uses:
  - The formal umbrella definition (from taxonomy_definitions.py)
  - The formal sub-category definitions (context only, not classified here)
  - The enriched insight content + metadata summary
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Optional

from recap.schemas.enrichment import EnrichedInsight
from recap.schemas.classification import ClassificationResult, UmbrellaLabel
from recap.llm.llm_client import LLMClient
from recap.taxonomy.taxonomy_definitions import (
    get_sub_category_block,
    get_umbrella_definition,
    UMBRELLA_DEFINITIONS,
)
from recap.prompts.prompts import (
    UMBRELLA_CLASSIFIER_SYSTEM_PROMPT,
    UMBRELLA_CLASSIFIER_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-umbrella classifier
# ---------------------------------------------------------------------------

async def _classify_one_umbrella(
    insight: EnrichedInsight,
    umbrella_key: str,
    llm: LLMClient,
) -> ClassificationResult:
    """
    Run a single umbrella classifier for one insight.
    Returns a ClassificationResult with value, confidence, and evidence.
    """
    umbrella_label = UMBRELLA_DEFINITIONS[umbrella_key]["label"]
    umbrella_definition = get_umbrella_definition(umbrella_key)
    sub_category_block = get_sub_category_block(umbrella_key)

    system_prompt = UMBRELLA_CLASSIFIER_SYSTEM_PROMPT.format(
        umbrella_label=umbrella_label,
        umbrella_definition=umbrella_definition,
        sub_category_block=sub_category_block,
    )

    md = insight.metadata
    user_message = UMBRELLA_CLASSIFIER_USER_TEMPLATE.format(
        deck_id=insight.deck_id,
        slide_number=insight.slide_number,
        section=insight.section or "(none)",
        slide_title=insight.slide_title or "(no title)",
        content_unit_id=insight.content_unit_id,
        content=insight.content,
        lobs=", ".join(md.lines_of_business) or "unknown",
        regions=", ".join(md.regions + md.countries) or "unknown",
        kpis=", ".join(md.kpis + md.metrics) or "unknown",
        performance_direction=md.performance_direction.value,
    )

    try:
        raw = await llm.call(
            system_prompt=system_prompt,
            user_message=user_message,
            max_completion_tokens=512,
        )
        d = json.loads(raw) if isinstance(raw, str) else raw
        # LLM sometimes returns integers [1, 2, 3] — coerce to strings
        raw_ids = d.get("evidence_element_ids", []) or []
        return ClassificationResult(
            umbrella=UmbrellaLabel(umbrella_key),
            value=bool(d.get("value", False)),
            confidence=float(d.get("confidence", 0.0)),
            evidence_element_ids=[str(i) for i in raw_ids],
            rationale=d.get("rationale"),
        )
    except Exception as exc:
        logger.warning(
            "Umbrella classifier failed for %s / %s: %s",
            insight.content_unit_id,
            umbrella_key,
            exc,
        )
        return ClassificationResult(
            umbrella=UmbrellaLabel(umbrella_key),
            value=False,
            confidence=0.0,
            evidence_element_ids=[],
            rationale=f"classifier_error: {exc}",
        )


# ---------------------------------------------------------------------------
# Umbrella classifier orchestrator
# ---------------------------------------------------------------------------

class UmbrellaClassifiers:
    """
    Runs all four umbrella classifiers concurrently for each insight.

    Usage
    -----
    classifiers = UmbrellaClassifiers(llm_client)
    results = await classifiers.classify(insight)
    # results is a dict: umbrella_key → ClassificationResult
    """

    UMBRELLA_KEYS = [
        "performance_and_position",
        "opportunity_and_growth",
        "market_and_external_context",
        "relationship_and_collaboration",
    ]

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self._llm = llm_client or LLMClient()

    async def classify(
        self, insight: EnrichedInsight
    ) -> dict[str, ClassificationResult]:
        """
        Run all four umbrella classifiers concurrently.
        Returns dict mapping umbrella_key → ClassificationResult.
        """
        tasks = {
            key: _classify_one_umbrella(insight, key, self._llm)
            for key in self.UMBRELLA_KEYS
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        output: dict[str, ClassificationResult] = {}
        for key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.error(
                    "Umbrella %s failed for %s: %s",
                    key, insight.content_unit_id, result,
                )
                output[key] = ClassificationResult(
                    umbrella=UmbrellaLabel(key),
                    value=False,
                    confidence=0.0,
                    evidence_element_ids=[],
                    rationale=f"gather_error: {result}",
                )
            else:
                output[key] = result

        active = [k for k, v in output.items() if v.value]
        logger.debug(
            "Umbrella classification for %s: active=%s",
            insight.content_unit_id,
            active,
        )
        return output

    async def classify_batch(
        self, insights: List[EnrichedInsight]
    ) -> List[dict[str, ClassificationResult]]:
        """Classify a batch of insights concurrently."""
        tasks = [self.classify(insight) for insight in insights]
        return await asyncio.gather(*tasks)
