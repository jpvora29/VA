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
import re
import asyncio
from typing import Optional

from recap.schemas.enrichment import EnrichedInsight, Urgency
from recap.schemas.action_item import ActionItemResult, AtomicAction
from recap.llm.llm_client import LLMClient
from recap.config import settings
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
        """Split bullets/sentences and classify each fragment independently."""
        fragments = self._split_fragments(insight.content)
        results = await asyncio.gather(*(self._classify_fragment(insight, text, idx) for idx, text in enumerate(fragments)), return_exceptions=True)
        actions = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Action fragment classification failed for %s: %s", insight.content_unit_id, result)
            elif result is not None and result.is_action_item:
                actions.extend(result.actions)
        if actions:
            first = actions[0]
            return ActionItemResult(content_unit_id=insight.content_unit_id, is_action_item=True, confidence=max(a.confidence for a in actions), evidence_element_ids=insight.source_element_ids, rationale="Atomic action classification across sentence/bullet fragments.", urgency=first.urgency, action_description=first.task, owner=first.owner, deadline=first.deadline, line_of_business=first.line_of_business, geography=first.geography, source_slide_number=insight.slide_number, source_section=insight.section, actions=actions)
        return ActionItemResult(content_unit_id=insight.content_unit_id, is_action_item=False, confidence=0.0, rationale="No fragment met the specific-task, owner, and forward-movement criteria.", urgency=Urgency.NONE, source_slide_number=insight.slide_number, source_section=insight.section)

    @staticmethod
    def _split_fragments(content: str) -> list[str]:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        fragments = []
        for line in lines:
            clean = re.sub(r"^(?:[-•▪*–]\s*|\d+[.)]\s*)", "", line).strip()
            if not clean or clean.startswith(("[TABLE", "[CHART", "Table (", "Chart:")):
                continue
            parts = re.split(r"(?<=[.!?])\s+", clean)
            fragments.extend(p.strip() for p in parts if p.strip())
        return fragments or [content.strip()]

    async def _classify_fragment(self, insight: EnrichedInsight, fragment: str, index: int) -> Optional[ActionItemResult]:
        user_message = ACTION_ITEM_USER_TEMPLATE.format(deck_id=insight.deck_id, slide_number=insight.slide_number, section=insight.section or "(none)", slide_title=insight.slide_title or "(no title)", content_unit_id=f"{insight.content_unit_id}#b{index:03d}", content=fragment)
        try:
            raw = await self._llm.call(system_prompt=ACTION_ITEM_SYSTEM_PROMPT, user_message=user_message, max_completion_tokens=settings.token_budget("action_item_classification"), reasoning_effort=settings.reasoning_effort_for("action_item_classification"), stage="action_item_classification")
            d = json.loads(raw) if isinstance(raw, str) else raw
            parsed = self._parse(insight, d)
            if not parsed.is_action_item:
                return parsed
            parsed.source_bullet_id = f"{insight.content_unit_id}#b{index:03d}"
            parsed.actions = [AtomicAction(task=parsed.action_description or fragment, owner=parsed.owner, deadline=parsed.deadline, geography=parsed.geography, line_of_business=parsed.line_of_business, source_bullet_id=parsed.source_bullet_id, source_element_ids=parsed.evidence_element_ids or insight.source_element_ids, confidence=parsed.confidence, urgency=parsed.urgency, rationale=parsed.rationale)]
            return parsed
        except Exception as exc:
            logger.warning("Action item fragment failed for %s: %s", insight.content_unit_id, exc)
            return None

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
            source_bullet_id=_str_or_none(d.get("source_bullet_id")),
            actions=[],
        )
