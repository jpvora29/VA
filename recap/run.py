"""One recap run, readable top to bottom.

    decks  ->  insights  ->  one recap  ->  recap.json + recap.pptx

:func:`run_recap_pipeline` is the order those happen in; each step is a named function
below and does one of them. The deck-level machinery (extraction, filtering, grouping,
enrichment, classification) belongs to :class:`recap.pipeline.BusinessReviewPipeline`;
this module is what turns *a user's request* into files on disk.

Every dependency that touches the outside world — the model, the progress sink — is
reached through something injected or replaceable, so the whole flow runs in a test
with a stub client and no credentials.

Several decks make ONE recap, not one recap each. They share an insight store and the
recap is generated from the store once everything is in it, which is the only way a
sentence can say "across both quarters" and mean it.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from logger import get_logger
from recap.config import RunPaths, settings
from recap.generation.pptx_renderer import PPTXRenderer
from recap.llm.llm_client import LLMClient
from recap.metadata import DeckMetadata, deck_id_for
from recap.pipeline.pipeline import BusinessReviewPipeline
from recap.progress import Reporter, silent
from recap.schemas.recap import RecapOutput
from recap.store.insight_store import InsightStore

log = get_logger(__name__)


@dataclass(frozen=True)
class RecapRequest:
    """What the user asked for: some decks, what they are about, and where to work."""

    deck_paths: Tuple[Path, ...]
    metadata: DeckMetadata
    paths: RunPaths
    template_path: Optional[Path] = None
    glossary_path: Optional[Path] = None

    def template(self) -> Path:
        return self.template_path or settings.default_template_path

    def glossary(self) -> Optional[Path]:
        chosen = self.glossary_path or settings.default_glossary_path
        return chosen if chosen and Path(chosen).exists() else None


@dataclass(frozen=True)
class RecapResult:
    """What the run produced."""

    pptx_path: Path
    recap_json_path: Path
    insight_store_path: Path
    deck_id: str
    client: str
    period: str
    takeaway_titles: List[str]
    action_item_count: int
    insight_count: int
    confidence: float


# ── the run ───────────────────────────────────────────────────────────────────


def run_recap_pipeline(
    request: RecapRequest,
    report: Reporter = silent,
    llm: Optional[LLMClient] = None,
) -> RecapResult:
    """Read the decks, write the recap, render the deck. Blocking: run it in a thread.

    ``llm`` is the one dependency worth injecting: pass a stub and the whole flow —
    extraction, filtering, grouping, classification, rendering, the files on disk —
    runs in a test without a credential."""
    report("staging")
    specs = build_deck_specs(request)
    store = InsightStore()

    recap = asyncio.run(read_decks(request, specs, store, report, llm))

    recap_json_path = save_recap_json(recap, request.paths)
    store_path = save_insight_store(store, request.paths)
    pptx_path = render_recap_deck(recap, request, report)

    return build_result(recap, store, pptx_path, recap_json_path, store_path)


# ── steps ─────────────────────────────────────────────────────────────────────


def build_deck_specs(request: RecapRequest) -> List[dict]:
    """One ``BusinessReviewPipeline.run`` argument set per uploaded deck.

    The metadata read off the cover slide is applied to every deck in the run: the
    user uploaded them as one review, and a deck whose own cover was unreadable
    should still be filed under the client the others named.
    """
    meta = request.metadata
    return [
        {
            "file_path": str(path),
            "deck_id": deck_id_for(path.name, index),
            "client_name": meta.client_name or None,
            "company_name": meta.company_name or None,
            "period_label": meta.period_label or None,
            "quarter": meta.quarter or None,
            "year": int(meta.year) if str(meta.year).isdigit() else None,
            "meeting_date": meta.meeting_date or None,
        }
        for index, path in enumerate(request.deck_paths)
    ]


async def read_decks(
    request: RecapRequest,
    specs: Sequence[dict],
    store: InsightStore,
    report: Reporter,
    llm: Optional[LLMClient] = None,
) -> RecapOutput:
    """Every deck into one insight store, then one recap out of it.

    Each deck gets its own pipeline because a pipeline holds one deck's stages, but
    they are handed the SAME store — that is what makes the recap cover all of them.
    """
    pipeline = None
    for index, spec in enumerate(specs, start=1):
        pipeline = BusinessReviewPipeline(
            glossary_path=request.glossary(),
            store=store,
            report=deck_reporter(report, Path(spec["file_path"]).name, index, len(specs)),
            outputs_dir=request.paths.artefacts,
            llm=llm,
        )
        await pipeline.run(generate_recap=False, **spec)

    report("recap")
    return await pipeline.generate_recap_from_store(
        deck_id=specs[0]["deck_id"],
        client_name=request.metadata.client_name or None,
        period_label=period_label(request.metadata),
        min_confidence=settings.recap_min_confidence,
    )


def save_recap_json(recap: RecapOutput, paths: RunPaths) -> Path:
    """The recap as data, beside the deck — what a later question is answered from."""
    path = paths.recap_json(recap.deck_id)
    path.write_text(
        json.dumps(recap.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def save_insight_store(store: InsightStore, paths: RunPaths) -> Path:
    """Every insight the recap was drawn from, so any sentence can be traced back."""
    store.save(paths.insight_store)
    return paths.insight_store


def render_recap_deck(recap: RecapOutput, request: RecapRequest, report: Reporter) -> Path:
    """The recap poured into the QBR Recap template."""
    report("rendering")
    output_path = request.paths.recap_pptx(recap.deck_id)
    return PPTXRenderer(request.template()).render(recap, output_path=output_path)


def build_result(
    recap: RecapOutput,
    store: InsightStore,
    pptx_path: Path,
    recap_json_path: Path,
    store_path: Path,
) -> RecapResult:
    """What the workspace shows once the run ends."""
    return RecapResult(
        pptx_path=Path(pptx_path),
        recap_json_path=recap_json_path,
        insight_store_path=store_path,
        deck_id=recap.deck_id,
        client=recap.client_name or "",
        period=recap.period_label or "",
        takeaway_titles=[t.title for t in recap.key_takeaways],
        action_item_count=len(recap.action_items),
        insight_count=store.count,
        confidence=recap.overall_confidence,
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def period_label(metadata: DeckMetadata) -> Optional[str]:
    """"Q2 2026", however the cover slide happened to state it."""
    if metadata.period_label:
        return metadata.period_label
    joined = " ".join(part for part in (metadata.quarter, metadata.year) if part)
    return joined or None


def deck_reporter(report: Reporter, name: str, index: int, total: int) -> Reporter:
    """A reporter that says which deck a stage is running for.

    With one deck the stage's own label is the whole story; with three, "Extracting
    slides" three times over looks like the run is stuck.
    """

    def report_stage(stage: str, message: str = "") -> None:
        report(stage, message or (f"{name} ({index} of {total})" if total > 1 else name))

    return report_stage
