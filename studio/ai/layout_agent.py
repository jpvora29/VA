"""Layout agent — picks each content slide's dense archetype.

The deterministic composer (`studio/deck/compose.py`) already produces a full,
valid slide. This agent only *chooses* which archetype id (from the fixed catalog)
each slide should use; the choice is stored in `slide.meta['archetype']` and
re-validated by `compose.apply_archetype`, so an unknown or impossible pick simply
falls back to the deterministic composition. No key → deck unchanged.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, List, Tuple

from logger import get_logger
from studio.ai.client import llm_available, structured
from studio.ai.models import DeckLayout
from studio.deck.archetypes import ARCHETYPES
from studio.deck.model import DeckSpec, SlideSpec

logger = get_logger(__name__)

_CONTENT_LAYOUTS = {"insight", "decision"}

_SYSTEM = """You arrange QBR slides. For each slide choose the archetype id that best
fills the frame, from the provided catalog only. Prefer a denser archetype when the
slide has a stat band and two visuals. Return one choice per idx; use only ids from
the catalog."""


def _payload(content: List[Tuple[int, SlideSpec]]) -> str:
    catalog = [
        {"id": a.name, "needs_stat_band": a.has_stat_band, "needs_secondary": a.has_secondary}
        for a in ARCHETYPES.values()
    ]
    slides = []
    for i, s in content:
        visuals = [b.kind for b in s.blocks if b.kind != "kpis"]
        slides.append({
            "idx": i,
            "has_kpis": any(b.kind == "kpis" for b in s.blocks),
            "has_evidence": bool(s.evidence),
            "visuals": visuals,
        })
    return json.dumps({"catalog": catalog, "slides": slides}, ensure_ascii=False)


def enhance_deck(deck: DeckSpec) -> DeckSpec:
    """Tag content slides with an AI-chosen archetype id, or return deck unchanged."""
    if not llm_available():
        return deck
    content = [(i, s) for i, s in enumerate(deck.slides) if s.layout in _CONTENT_LAYOUTS]
    if not content:
        return deck

    layout = structured(DeckLayout, _SYSTEM, _payload(content), node="layout")
    if layout is None:
        return deck

    by_idx = {c.idx: c.archetype for c in layout.choices}
    slides = list(deck.slides)
    tagged = 0
    for i, s in content:
        choice = by_idx.get(i)
        if choice in ARCHETYPES:
            slides[i] = replace(s, meta={**(s.meta or {}), "archetype": choice})
            tagged += 1
    logger.info("studio.ai layout tagged %d/%d slides", tagged, len(content))
    return replace(deck, slides=tuple(slides))
