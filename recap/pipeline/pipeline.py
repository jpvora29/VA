"""
pipeline/pipeline.py

Stage 12 — Async Pipeline Orchestrator.

Coordinates all stages end-to-end with controlled concurrency:

  Per-deck:
    1. Raw extraction (sync, python-pptx)
    2. Noise filtering (async — per-slide with LLM ambiguous pass)
    3. Semantic content unit construction (sync per slide)

  Per-SCU (concurrent across all SCUs in the deck):
    4. Metadata enrichment (async LLM)

  Per-enriched insight (concurrent, 4 umbrella LLMs per insight):
    5. Umbrella classification (4 concurrent async LLMs)
    6. Sub-category classification (concurrent, only for active umbrellas)
    7. Action item classification (async LLM, independent)

  8. Assemble StructuredInsight and save to InsightStore
  9. Generate recap from InsightStore

Concurrency controls:
  - Global semaphore on LLM calls (settings.max_concurrent_llm_calls)
  - Per-stage semaphore on insight-level classification to avoid fan-out
  - Configurable batch size for enrichment

All errors are caught per-unit; one bad SCU never aborts the pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from recap.config import settings
from recap.extraction.extractor import PPTExtractor
from recap.filtering.noise_filter import NoiseFilter
from recap.grouping.content_units import ContentUnitBuilder
from recap.glossary.glossary import BusinessGlossary
from recap.enrichment.enrichment import EnrichmentLLM
from recap.classification.umbrella_classifiers import UmbrellaClassifiers
from recap.classification.subcategory_classifier import SubCategoryClassifier
from recap.classification.action_item_classifier import ActionItemClassifier
from recap.store.insight_store import InsightStore, assemble_insight
from recap.generation.recap_generator import RecapGenerator
from recap.schemas.raw_extraction import RawDeck
from recap.schemas.content_units import SemanticContentUnit
from recap.schemas.enrichment import EnrichedInsight
from recap.schemas.recap import RecapOutput
from recap.llm.llm_client import LLMClient
from recap.progress import Reporter, silent

logger = logging.getLogger(__name__)


class BusinessReviewPipeline:
    """
    End-to-end pipeline: .pptx files → StructuredInsightStore → RecapOutput.

    Usage
    -----
    pipeline = BusinessReviewPipeline(glossary_path="glossary.json")

    recap = await pipeline.run(
        file_path="decks/client_q2_2026.pptx",
        deck_id="client_q2_2026",
        meeting_date="2026-04-01",
        quarter="Q2",
        year=2026,
        client_name="Acme Corp",
    )

    # Access the store for further querying / auditing
    insights = pipeline.store.query(umbrella="performance_and_position")
    trace   = pipeline.store.trace("INS_client_q2_2026_CU_...")
    """

    def __init__(
        self,
        glossary_path: Optional[str | Path] = None,
        store: Optional[InsightStore] = None,
        report: Reporter = silent,
        outputs_dir: Optional[str | Path] = None,
        llm: Optional[LLMClient] = None,
    ) -> None:
        # Shared LLM client - ONE semaphore for the whole pipeline, which is what
        # bounds its fan-out. Injectable so the whole run is testable with a stub
        # and no credentials.
        self._llm = llm or LLMClient()

        # Where the run announces the stage it is entering (``recap.progress``).
        # A stage id, never prose: the bar reads the id's percentage, so rewording
        # a label cannot break the progress it drives.
        self._report = report

        # Optional directory for saving raw/tagged output artefacts
        self._outputs_dir: Optional[Path] = Path(outputs_dir) if outputs_dir else None
        if self._outputs_dir:
            self._outputs_dir.mkdir(parents=True, exist_ok=True)

        # Stages
        self._extractor    = PPTExtractor()
        self._noise_filter = NoiseFilter(self._llm)
        self._cu_builder   = ContentUnitBuilder()
        self._glossary     = (
            BusinessGlossary.from_file(glossary_path)
            if glossary_path
            else BusinessGlossary()
        )
        self._enricher           = EnrichmentLLM(self._llm, self._glossary)
        self._umbrella_clf       = UmbrellaClassifiers(self._llm)
        self._subcategory_clf    = SubCategoryClassifier(self._llm)
        self._action_item_clf    = ActionItemClassifier(self._llm)
        self._recap_generator    = RecapGenerator(self._llm)

        # Shared insight store (can be pre-populated for multi-deck runs)
        self.store: InsightStore = store or InsightStore()

        # Per-insight classification semaphore (prevents excessive fan-out)
        self._classify_sem = None  # lazy-init inside running event loop

    # ----------------------------------------------------------------
    # Artefact saving helper
    # ----------------------------------------------------------------

    def _save_artefact(self, deck_id: str, suffix: str, data: object) -> None:
        """
        Serialise *data* to outputs_dir/{deck_id}_{suffix}.json.
        Silently skips if outputs_dir is not set or serialisation fails.
        """
        if not self._outputs_dir:
            return
        try:
            if hasattr(data, "model_dump"):
                payload = data.model_dump(mode="json")
            elif isinstance(data, list):
                payload = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in data
                ]
            else:
                payload = data
            out = self._outputs_dir / f"{deck_id}_{suffix}.json"
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Saved artefact: %s", out.name)
        except Exception as exc:
            logger.warning("Could not save artefact %s_%s: %s", deck_id, suffix, exc)

    # ----------------------------------------------------------------
    # Public entry points
    # ----------------------------------------------------------------

    async def run(
        self,
        file_path: str | Path,
        deck_id: str,
        meeting_date: Optional[str] = None,
        quarter: Optional[str] = None,
        half_year: Optional[str] = None,
        year: Optional[int] = None,
        period_label: Optional[str] = None,
        client_name: Optional[str] = None,
        company_name: Optional[str] = None,
        generate_recap: bool = True,
        min_recap_confidence: float = 0.0,
        store_output_path: Optional[str | Path] = None,
    ) -> RecapOutput:
        """
        Run the full pipeline for a single deck.

        Parameters
        ----------
        file_path            : Path to the .pptx file.
        deck_id              : Unique deck identifier.
        meeting_date         : ISO-8601 meeting date.
        quarter / half_year  : Period granularity labels.
        year                 : Calendar year.
        period_label         : Free-form label, e.g. 'Q2 2026 QBR'.
        client_name          : Client name (used for noise filtering & recap).
        company_name         : Company name (used for noise filtering).
        generate_recap       : Whether to call the recap generator at the end.
        min_recap_confidence : Minimum insight confidence for recap inclusion.
        store_output_path    : If set, save the InsightStore to this JSON path.

        Returns
        -------
        RecapOutput — structured recap ready for presentation.
        """
        t0 = time.perf_counter()
        logger.info("=== Pipeline START: deck_id=%s ===", deck_id)

        # ── Stage 1: Raw extraction ──────────────────────────────────
        self._report("extracting")
        deck = self._extract(
            file_path, deck_id, meeting_date, quarter,
            half_year, year, period_label, client_name, company_name,
        )
        self._save_artefact(deck_id, "01_raw_extraction", deck)

        # ── Stages 2–3: Noise filter + SCU construction ─────────────
        self._report("filtering")
        all_scus = await self._filter_and_group(deck)
        self._report("grouping")
        logger.info("Total SCUs built: %d", len(all_scus))
        self._save_artefact(deck_id, "02_content_units", all_scus)

        if not all_scus:
            logger.warning("No SCUs produced for deck_id=%s", deck_id)
            self._report("recap", "No usable content was found in this deck.")
            return RecapGenerator._empty_recap(deck_id, client_name, period_label)

        # ── Stage 4: Metadata enrichment ────────────────────────────
        self._report("enriching")
        enriched_insights = await self._enrich(all_scus, deck)
        logger.info("Enriched insights: %d", len(enriched_insights))
        self._save_artefact(deck_id, "03_enriched_insights", enriched_insights)

        # ── Stages 5–7: Classification (concurrent per insight) ──────
        self._report("classifying")
        structured_insights = await self._classify_all(enriched_insights, deck)
        logger.info("Structured insights assembled: %d", len(structured_insights))
        self._save_artefact(deck_id, "04_tagged_insights", structured_insights)

        # ── Stage 8: Persist to store ────────────────────────────────
        self._report("storing")
        self.store.add_many(structured_insights)
        if store_output_path:
            self.store.save(store_output_path)

        # ── Stage 9: Recap generation ────────────────────────────────
        if not generate_recap:
            return RecapGenerator._empty_recap(deck_id, client_name, period_label)

        self._report("recap")
        recap = await self.generate_recap_from_store(
            deck_id=deck_id,
            client_name=client_name,
            period_label=period_label or deck.period_label,
            min_confidence=min_recap_confidence,
        )

        elapsed = time.perf_counter() - t0
        logger.info(
            "=== Pipeline DONE: deck_id=%s  insights=%d  elapsed=%.1fs ===",
            deck_id,
            len(structured_insights),
            elapsed,
        )
        return recap

    async def generate_recap_from_store(
        self,
        *,
        deck_id: str,
        client_name: Optional[str] = None,
        period_label: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> RecapOutput:
        """
        Generate one recap from everything the insight store currently holds.

        `run()` calls this at its own last stage. It is public because a run over
        SEVERAL decks wants exactly one recap covering all of them: the caller runs
        each deck with `generate_recap=False` into a shared store, then asks here.
        """
        return await self._recap_generator.generate(
            store=self.store,
            deck_id=deck_id,
            client_name=client_name,
            period_label=period_label,
            min_confidence=min_confidence,
        )

    async def run_multiple(
        self,
        decks: List[Dict],
        generate_recap_per_deck: bool = True,
        store_output_path: Optional[str | Path] = None,
    ) -> Dict[str, RecapOutput]:
        """
        Run the pipeline for multiple decks sequentially (extraction) but
        with full async concurrency within each deck.

        Parameters
        ----------
        decks : List of dicts, each with keys matching `run()` parameters.
                Required keys: file_path, deck_id.
        generate_recap_per_deck : Whether to generate a recap per deck.
        store_output_path : If set, save the combined store after all decks.

        Returns
        -------
        Dict mapping deck_id → RecapOutput.
        """
        results: Dict[str, RecapOutput] = {}
        for deck_kwargs in decks:
            deck_id = deck_kwargs["deck_id"]
            try:
                recap = await self.run(
                    generate_recap=generate_recap_per_deck,
                    **deck_kwargs,
                )
                results[deck_id] = recap
            except Exception as exc:
                logger.error("Pipeline failed for deck_id=%s: %s", deck_id, exc)
                results[deck_id] = RecapGenerator._empty_recap(
                    deck_id,
                    deck_kwargs.get("client_name"),
                    deck_kwargs.get("period_label"),
                )

        if store_output_path:
            self.store.save(store_output_path)

        return results

    # ----------------------------------------------------------------
    # Stage implementations
    # ----------------------------------------------------------------

    def _extract(
        self,
        file_path, deck_id, meeting_date, quarter,
        half_year, year, period_label, client_name, company_name,
    ) -> RawDeck:
        logger.info("Stage 1: Extracting %s", file_path)
        return self._extractor.extract(
            file_path=file_path,
            deck_id=deck_id,
            meeting_date=meeting_date,
            quarter=quarter,
            half_year=half_year,
            year=year,
            period_label=period_label,
            client_name=client_name,
            company_name=company_name,
        )

    async def _filter_and_group(
        self, deck: RawDeck
    ) -> List[SemanticContentUnit]:
        """
        Stages 2 & 3: filter all slides concurrently, then build SCUs.
        """
        logger.info("Stage 2: Noise filtering (%d slides)", deck.total_slides)
        filtered_slides = await self._noise_filter.filter_deck(deck)

        # Map slide_number → FilteredSlide for fast lookup
        filtered_map = {fs.slide_number: fs for fs in filtered_slides}

        all_scus: List[SemanticContentUnit] = []
        logger.info("Stage 3: Building semantic content units")
        for slide in deck.slides:
            fs = filtered_map.get(slide.slide_number)
            if fs is None:
                continue
            kept = self._noise_filter.get_kept_elements(slide, fs)
            scus = self._cu_builder.build(slide, kept)
            all_scus.extend(scus)

        return all_scus

    async def _enrich(
        self,
        scus: List[SemanticContentUnit],
        deck: RawDeck,
    ) -> List[EnrichedInsight]:
        """Stage 4: Enrich all SCUs with business metadata."""
        logger.info("Stage 4: Enriching %d SCUs", len(scus))
        return await self._enricher.enrich_deck(scus, deck)

    async def _classify_all(
        self,
        insights: List[EnrichedInsight],
        deck: RawDeck,
    ) -> list:
        """
        Stages 5–7: Classify each insight concurrently.
        Uses a semaphore to prevent unbounded fan-out.
        """
        # Lazy-init semaphore inside the running event loop
        if self._classify_sem is None:
            self._classify_sem = asyncio.Semaphore(
                settings.max_concurrent_insight_classification
            )

        logger.info(
            "Stages 5-7: Classifying %d enriched insights", len(insights)
        )
        tasks = [self._classify_one(ins, deck) for ins in insights]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        structured = []
        for ins, result in zip(insights, results):
            if isinstance(result, Exception):
                logger.error(
                    "Classification failed for %s: %s",
                    ins.content_unit_id,
                    result,
                )
            else:
                structured.append(result)
        return structured

    async def _classify_one(self, insight: EnrichedInsight, deck: RawDeck):
        """
        Classify a single insight through all classifier stages.
        Runs umbrella classifiers + action item classifier concurrently,
        then sub-category classifiers for active umbrellas.
        """
        async with self._classify_sem:
            # Stages 5 + 7 concurrently: 4 umbrella LLMs + action item LLM
            umbrella_task     = self._umbrella_clf.classify(insight)
            action_item_task  = self._action_item_clf.classify(insight)
            umbrella_results, action_item_result = await asyncio.gather(
                umbrella_task, action_item_task
            )

            # Stage 6: sub-category (only for active umbrellas)
            sub_category_results = await self._subcategory_clf.classify(
                insight, umbrella_results
            )

        return assemble_insight(
            enriched=insight,
            umbrella_results=umbrella_results,
            sub_category_results=sub_category_results,
            action_item_result=action_item_result,
            deck=deck,
        )
