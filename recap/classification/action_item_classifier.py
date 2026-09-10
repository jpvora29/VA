"""
classification/action_item_classifier.py

Stage 10 — Action Item Classification.

Independent from umbrella classification: every insight is evaluated
for action-item status regardless of its umbrella membership.

Determines:
  - is_action_item: bool
  - urgency: high / medium / low / unknown / none
  - action details: description, owner, deadline, LOB, geography

The model never invents urgency without textual evidence.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from recap.schemas.enrichment import EnrichedInsight, Urgency
from recap.schemas.action_item import ActionItemResult
from recap.llm.llm_client import LLMClient
from recap.prompts.prompts import (
    ACTION_ITEM_SYSTEM_PROMPT,
    ACTION_ITEM_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


class ActionItemClassifier:
    """
    Classifies whether an EnrichedInsight contains an action item.

    Usage
    -----
    classifier = ActionItemClassifier(llm_client)
    result = await classifier.classify(insight)
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self._llm = llm_client or LLMClient()

    async def classify(self, insight: EnrichedInsight) -> ActionItemResult:
        """Classify a single insight for action-item status."""
        user_message = ACTION_ITEM_USER_TEMPLATE.format(
            deck_id=insight.deck_id,
            slide_number=insight.slide_number,
            section=insight.section or "(none)",
            slide_title=insight.slide_title or "(no title)",
            content_unit_id=insight.content_unit_id,
            content=insight.content,
        )

        try:
            raw = await self._llm.call(
                system_prompt=ACTION_ITEM_SYSTEM_PROMPT,
                user_message=user_message,
                max_completion_tokens=512,
            )
            d = json.loads(raw) if isinstance(raw, str) else raw
            return self._parse(insight, d)

        except Exception as exc:
            logger.warning(
                "Action item classification failed for %s: %s",
                insight.content_unit_id,
                exc,
            )
            return ActionItemResult(
                content_unit_id=insight.content_unit_id,
                is_action_item=False,
                confidence=0.0,
                rationale=f"classifier_error: {exc}",
                urgency=Urgency.UNKNOWN,
                source_slide_number=insight.slide_number,
                source_section=insight.section,
            )

    def _parse(self, insight: EnrichedInsight, d: dict) -> ActionItemResult:
        def _str_or_none(v) -> Optional[str]:
            return None if v in (None, "null", "unknown", "") else str(v)

        def _urgency(v) -> Urgency:
            try:
                return Urgency(str(v).lower())
            except Exception:
                return Urgency.UNKNOWN

        def _conf(v) -> float:
            try:
                return max(0.0, min(1.0, float(v)))
            except Exception:
                return 0.0

        is_action = bool(d.get("is_action_item", False))
        urgency = _urgency(d.get("urgency", "none")) if is_action else Urgency.NONE

        return ActionItemResult(
            content_unit_id=insight.content_unit_id,
            is_action_item=is_action,
            confidence=_conf(d.get("confidence", 0.0)),
            evidence_element_ids=d.get("evidence_element_ids", []),
            rationale=_str_or_none(d.get("rationale")),
            urgency=urgency,
            urgency_confidence=_conf(d.get("urgency_confidence", 0.0)),
            urgency_rationale=_str_or_none(d.get("urgency_rationale")),
            action_description=_str_or_none(d.get("action_description")),
            owner=_str_or_none(d.get("owner")),
            deadline=_str_or_none(d.get("deadline")),
            line_of_business=_str_or_none(d.get("line_of_business")),
            geography=_str_or_none(d.get("geography")),
            source_slide_number=insight.slide_number,
            source_section=insight.section,
        )
