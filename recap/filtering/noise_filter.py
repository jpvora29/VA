"""
filtering/noise_filter.py

Stage 2 — Noise Filtering.

Orchestrates two passes:
  Pass 1 (fast, free): Rule-based — handles obvious noise and obvious content.
  Pass 2 (LLM):        Ambiguous cases where rule confidence < AMBIGUITY_THRESHOLD.

The raw extraction is NEVER modified. All decisions are stored in a separate
FilteredSlide overlay. Every decision (keep or remove) is auditable and reversible.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Optional

from recap.schemas.raw_extraction import RawDeck, RawElement, RawSlide
from recap.schemas.filtered import FilterDecision, FilterReason, FilteredSlide
from recap.llm.llm_client import LLMClient
from recap.prompts.prompts import NOISE_FILTER_SYSTEM_PROMPT
from .rules import AMBIGUITY_THRESHOLD, apply_rules

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM ambiguous-case resolver
# ---------------------------------------------------------------------------

class _AmbiguousCaseDecision:
    """Lightweight parse target for the noise-filter LLM response."""
    def __init__(self, is_noise: bool, reason: str, confidence: float) -> None:
        self.is_noise = is_noise
        self.reason = reason
        self.confidence = confidence

    @classmethod
    def from_json(cls, raw: str) -> "_AmbiguousCaseDecision":
        try:
            d = json.loads(raw)
            return cls(
                is_noise=bool(d.get("is_noise", False)),
                reason=str(d.get("reason", "")),
                confidence=float(d.get("confidence", 0.5)),
            )
        except Exception:
            # If LLM response can't be parsed, default to keep (safe)
            return cls(is_noise=False, reason="parse_error_defaulted_to_keep", confidence=0.5)


async def _resolve_ambiguous(
    element: RawElement,
    slide: RawSlide,
    rule_decision: FilterDecision,
    llm: LLMClient,
) -> FilterDecision:
    """
    Call the LLM to resolve a single ambiguous element.
    Builds a rich context message with the element + slide context.
    """
    context_parts = [
        f"Slide {slide.slide_number}: {slide.title or '(no title)'}",
        f"Section: {slide.section or '(none)'}",
        f"Element ID: {element.element_id}",
        f"Element type: {element.element_type.value}",
        f"Position: x={element.x}, y={element.y}, "
        f"w={element.width}, h={element.height}",
        f"Is footer placeholder: {element.is_placeholder and element.placeholder_type in ('FOOTER', 'SLIDE_NUMBER', 'DATE_AND_TIME')}",
        f"Font size: {element.font_size}",
        f"Text: {element.text!r}",
    ]

    # Include nearby elements for spatial context
    nearby = _nearby_element_texts(element, slide)
    if nearby:
        context_parts.append(f"Nearby element texts: {nearby}")

    context_parts.append(
        f"\nRule that flagged this as ambiguous: {rule_decision.rule_triggered}"
    )

    user_message = "\n".join(context_parts)

    try:
        raw_response = await llm.call_cheap(
            system_prompt=NOISE_FILTER_SYSTEM_PROMPT,
            user_message=user_message,
        )
        parsed = _AmbiguousCaseDecision.from_json(raw_response)
        return FilterDecision(
            element_id=element.element_id,
            is_noise=parsed.is_noise,
            reason=FilterReason.LLM_AMBIGUOUS,
            rule_triggered=rule_decision.rule_triggered,
            llm_used=True,
            llm_rationale=parsed.reason,
            confidence=parsed.confidence,
        )
    except Exception as exc:
        logger.warning(
            "LLM noise resolution failed for %s: %s — defaulting to keep",
            element.element_id,
            exc,
        )
        return FilterDecision(
            element_id=element.element_id,
            is_noise=False,
            reason=FilterReason.RETAINED,
            rule_triggered="llm_error_defaulted_to_keep",
            llm_used=True,
            llm_rationale=str(exc),
            confidence=0.5,
        )


def _nearby_element_texts(element: RawElement, slide: RawSlide) -> List[str]:
    """
    Return text snippets from elements spatially close to `element`
    (within ~1 inch = 914,400 EMU) to provide grouping context.
    """
    PROXIMITY_EMU = 914_400
    texts: List[str] = []
    if element.x is None or element.y is None:
        return texts
    for other in slide.elements:
        if other.element_id == element.element_id:
            continue
        if other.x is None or other.y is None:
            continue
        dx = abs(other.x - element.x)
        dy = abs(other.y - element.y)
        if dx < PROXIMITY_EMU and dy < PROXIMITY_EMU:
            t = other.effective_text()
            if t:
                texts.append(repr(t[:80]))
    return texts[:6]   # cap at 6 neighbours


# ---------------------------------------------------------------------------
# Main filter class
# ---------------------------------------------------------------------------

class NoiseFilter:
    """
    Applies two-pass noise filtering to a RawDeck.

    Pass 1 — Rule-based: fast, free, handles the majority of cases.
    Pass 2 — LLM: only for ambiguous elements (confidence < threshold).

    Usage
    -----
    nf = NoiseFilter(llm_client)
    filtered_slides = await nf.filter_deck(raw_deck)
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self._llm = llm_client or LLMClient()

    async def filter_deck(self, deck: RawDeck) -> List[FilteredSlide]:
        """Filter all slides in a deck concurrently."""
        tasks = [self.filter_slide(slide, deck) for slide in deck.slides]
        return await asyncio.gather(*tasks)

    async def filter_slide(
        self, slide: RawSlide, deck: RawDeck
    ) -> FilteredSlide:
        """
        Filter all elements on one slide.
        Pass 1 (rules) runs synchronously; ambiguous cases are gathered
        into a single async batch for the LLM pass.
        """
        # --- Pass 1: Rules ---
        rule_decisions: Dict[str, FilterDecision] = {}
        ambiguous: List[RawElement] = []

        for element in slide.elements:
            decision = apply_rules(
                element,
                client_name=deck.client_name,
                company_name=deck.company_name,
            )
            rule_decisions[element.element_id] = decision
            if decision.confidence < AMBIGUITY_THRESHOLD:
                ambiguous.append(element)

        # --- Pass 2: LLM (ambiguous cases only) ---
        if ambiguous:
            logger.debug(
                "Slide %d: %d/%d elements forwarded to LLM noise pass",
                slide.slide_number,
                len(ambiguous),
                len(slide.elements),
            )
            llm_tasks = [
                _resolve_ambiguous(
                    el, slide, rule_decisions[el.element_id], self._llm
                )
                for el in ambiguous
            ]
            llm_decisions = await asyncio.gather(*llm_tasks)
            for d in llm_decisions:
                rule_decisions[d.element_id] = d

        filtered = FilteredSlide(
            deck_id=deck.deck_id,
            slide_number=slide.slide_number,
            decisions=list(rule_decisions.values()),
        )

        kept = len(filtered.kept_element_ids())
        removed = len(filtered.removed_element_ids())
        logger.debug(
            "Slide %d filtered: kept=%d  removed=%d  llm_used=%d",
            slide.slide_number,
            kept,
            removed,
            len(ambiguous),
        )
        return filtered

    def get_kept_elements(
        self, slide: RawSlide, filtered_slide: FilteredSlide
    ) -> List[RawElement]:
        """
        Convenience: returns only the non-noise RawElements from a slide,
        in their original order.
        """
        kept_ids = set(filtered_slide.kept_element_ids())
        return [el for el in slide.elements if el.element_id in kept_ids]
