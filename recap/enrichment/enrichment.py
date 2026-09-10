"""
enrichment/enrichment.py

Stage 5 — Metadata / Semantic Enrichment.

Takes each SemanticContentUnit and runs TWO sequential LLM passes to
extract structured business metadata:

  Pass 1 — Context enrichment (ENRICHMENT_CONTEXT):
    Extracts organisational scope: lines of business, countries, regions.

  Pass 2 — KPI / Performance enrichment (ENRICHMENT_KPI):
    Extracts quantitative signals: KPIs, metrics, performance direction,
    growth details, update-type flags, owner, deadline.

Both passes receive the same content unit text, slide context, and
relevant glossary definitions. Results are merged into a single
InsightMetadata object.

Output is a strictly typed EnrichedInsight via Pydantic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Optional

from recap.schemas.content_units import SemanticContentUnit
from recap.schemas.enrichment import (
    EnrichedInsight,
    GrowthType,
    InsightMetadata,
    PerformanceDirection,
)
from recap.schemas.raw_extraction import RawDeck
from recap.glossary.glossary import BusinessGlossary
from recap.llm.llm_client import LLMClient
from recap.config import settings
from recap.prompts.prompts import (
    ENRICHMENT_CONTEXT_SYSTEM_PROMPT,
    ENRICHMENT_CONTEXT_USER_TEMPLATE,
    ENRICHMENT_KPI_SYSTEM_PROMPT,
    ENRICHMENT_KPI_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


class EnrichmentLLM:
    """
    Enriches a list of SemanticContentUnits with business metadata using
    two sequential LLM passes per unit:
      1. Context pass  — LoB, countries, regions
      2. KPI pass      — KPIs, metrics, performance, flags, ownership

    Usage
    -----
    enricher = EnrichmentLLM(llm_client, glossary)
    enriched_insights = await enricher.enrich_deck(scus_by_slide, deck)
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        glossary: Optional[BusinessGlossary] = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._glossary = glossary or BusinessGlossary()

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    async def enrich_deck(
        self,
        all_scus: List[SemanticContentUnit],
        deck: RawDeck,
    ) -> List[EnrichedInsight]:
        """
        Enrich all SCUs from a deck concurrently.
        Returns a flat list of EnrichedInsights in the same order.
        """
        tasks = [self.enrich_scu(scu, deck) for scu in all_scus]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched: List[EnrichedInsight] = []
        for scu, result in zip(all_scus, results):
            if isinstance(result, Exception):
                logger.error(
                    "Enrichment failed for %s: %s — using empty metadata",
                    scu.content_unit_id,
                    result,
                )
                enriched.append(self._empty_enriched(scu, deck))
            else:
                enriched.append(result)
        return enriched

    async def enrich_scu(
        self,
        scu: SemanticContentUnit,
        deck: RawDeck,
    ) -> EnrichedInsight:
        """
        Enrich a single SemanticContentUnit using two sequential LLM passes.

        Pass 1 — Context: LoB, countries, regions, glossary terms.
        Pass 2 — KPI / Performance: KPIs, metrics, direction, flags, ownership.

        The two passes run sequentially (Pass 2 is independent of Pass 1's
        output, but we keep them sequential to avoid unnecessary fan-out and
        to stay within concurrency budgets).
        """
        # Retrieve relevant glossary terms (shared across both passes)
        matched_terms = self._glossary.retrieve_for_context(
            content=scu.content,
            slide_title=scu.slide_title,
            section=scu.section,
        )
        glossary_block = BusinessGlossary.to_prompt_block(matched_terms)
        glossary_term_names = [t.term for t in matched_terms]

        # Shared formatting kwargs for both user templates
        template_kwargs = dict(
            deck_id=deck.deck_id,
            period_label=deck.period_label or "",
            slide_number=scu.slide_number,
            slide_title=scu.slide_title or "(no title)",
            section=scu.section or "(none)",
            content_unit_id=scu.content_unit_id,
            content=scu.content,
        )

        # ── Pass 1: Context (LoB, countries, regions) ──────────────
        context_block = settings.context_block()
        lob_list      = ", ".join(settings.lines_of_business) or "(none defined)"
        segment_list  = ", ".join(settings.segments) or "(none defined)"
        context_system = ENRICHMENT_CONTEXT_SYSTEM_PROMPT.format(
            context_block=context_block,
            lob_list=lob_list,
            segment_list=segment_list,
            glossary_block=glossary_block,
        )
        context_user = ENRICHMENT_CONTEXT_USER_TEMPLATE.format(
            **template_kwargs,
            lob_list=lob_list,
            segment_list=segment_list,
        )

        raw_context = await self._llm.call(
            system_prompt=context_system,
            user_message=context_user,
            max_completion_tokens=600,
        )

        # ── Pass 2: KPI / Performance ───────────────────────────────
        kpi_system = ENRICHMENT_KPI_SYSTEM_PROMPT.format(
            context_block=context_block,
            glossary_block=glossary_block,
        )
        kpi_user = ENRICHMENT_KPI_USER_TEMPLATE.format(**template_kwargs)

        raw_kpi = await self._llm.call(
            system_prompt=kpi_system,
            user_message=kpi_user,
            max_completion_tokens=1024,
        )

        # ── Merge both passes into InsightMetadata ──────────────────
        metadata = self._merge_metadata(
            raw_context, raw_kpi, scu.source_element_ids
        )

        return EnrichedInsight(
            content_unit_id=scu.content_unit_id,
            deck_id=scu.deck_id,
            slide_number=scu.slide_number,
            section=scu.section,
            slide_title=scu.slide_title,
            content=scu.content,
            source_element_ids=scu.source_element_ids,
            metadata=metadata,
            glossary_terms_used=glossary_term_names,
        )

    # ----------------------------------------------------------------
    # Parsing & Merging
    # ----------------------------------------------------------------

    def _merge_metadata(
        self,
        raw_context: str,
        raw_kpi: str,
        source_element_ids: List[str],
    ) -> InsightMetadata:
        """
        Parse both LLM JSON responses and merge them into one InsightMetadata.
        Falls back to safe empty defaults on any parse error.
        """
        try:
            ctx = json.loads(raw_context) if isinstance(raw_context, str) else raw_context
        except Exception as exc:
            logger.warning("Context metadata JSON parse failed: %s", exc)
            ctx = {}

        try:
            kpi = json.loads(raw_kpi) if isinstance(raw_kpi, str) else raw_kpi
        except Exception as exc:
            logger.warning("KPI metadata JSON parse failed: %s", exc)
            kpi = {}

        def _str_or_none(val) -> Optional[str]:
            if val in (None, "null", "unknown", ""):
                return None
            return str(val)

        def _list_of_str(val) -> List[str]:
            if not val:
                return []
            if isinstance(val, list):
                return [str(v) for v in val if v and str(v) not in ("null", "unknown")]
            return []

        def _perf_dir(val) -> PerformanceDirection:
            try:
                return PerformanceDirection(str(val).lower())
            except Exception:
                return PerformanceDirection.UNKNOWN

        def _growth_type(val) -> Optional[GrowthType]:
            if val in (None, "null", "unknown"):
                return None
            try:
                return GrowthType(str(val).lower())
            except Exception:
                return None

        def _confidence(val) -> float:
            try:
                c = float(val)
                return max(0.0, min(1.0, c))
            except Exception:
                return 0.0

        # Average the two confidence scores for the merged overall confidence
        ctx_conf = _confidence(ctx.get("overall_confidence", 0.0))
        kpi_conf = _confidence(kpi.get("overall_confidence", 0.0))
        merged_confidence = round((ctx_conf + kpi_conf) / 2, 4)

        # Merge matched_glossary_terms from both passes (deduplicated)
        merged_glossary = list(dict.fromkeys(
            _list_of_str(ctx.get("matched_glossary_terms"))
            + _list_of_str(kpi.get("matched_glossary_terms"))
        ))

        # Restrict LoB and segments to canonical lists from config
        canonical_lobs = {v.lower() for v in settings.lines_of_business}
        canonical_segs = {v.lower() for v in settings.segments}

        raw_lobs = _list_of_str(ctx.get("lines_of_business"))
        filtered_lobs = [v for v in raw_lobs if v.lower() in canonical_lobs]

        raw_segs = _list_of_str(ctx.get("segments"))
        filtered_segs = [v for v in raw_segs if v.lower() in canonical_segs]

        return InsightMetadata(
            # From Pass 1 — Context
            lines_of_business=filtered_lobs,
            segments=filtered_segs,
            countries=_list_of_str(ctx.get("countries")),
            regions=_list_of_str(ctx.get("regions")),
            # From Pass 2 — KPI / Performance
            kpis=_list_of_str(kpi.get("kpis")),
            metrics=_list_of_str(kpi.get("metrics")),
            performance_direction=_perf_dir(kpi.get("performance_direction", "unknown")),
            growth_type=_growth_type(kpi.get("growth_type")),
            growth_value=_str_or_none(kpi.get("growth_value")),
            baseline_value=_str_or_none(kpi.get("baseline_value")),
            current_value=_str_or_none(kpi.get("current_value")),
            is_client_update=bool(kpi.get("is_client_update", False)),
            is_company_update=bool(kpi.get("is_company_update", False)),
            is_market_condition=bool(kpi.get("is_market_condition", False)),
            is_opportunity=bool(kpi.get("is_opportunity", False)),
            is_concern=bool(kpi.get("is_concern", False)),
            owner=_str_or_none(kpi.get("owner")),
            deadline=_str_or_none(kpi.get("deadline")),
            matched_glossary_terms=merged_glossary,
            overall_confidence=merged_confidence,
        )

    # ----------------------------------------------------------------
    # Safe fallback
    # ----------------------------------------------------------------

    @staticmethod
    def _empty_enriched(scu: SemanticContentUnit, deck: RawDeck) -> EnrichedInsight:
        return EnrichedInsight(
            content_unit_id=scu.content_unit_id,
            deck_id=scu.deck_id,
            slide_number=scu.slide_number,
            section=scu.section,
            slide_title=scu.slide_title,
            content=scu.content,
            source_element_ids=scu.source_element_ids,
            metadata=InsightMetadata(),
            glossary_terms_used=[],
        )
