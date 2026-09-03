"""Story agent — sharper executive prose over the deterministic deck.

Rewrites each content slide's action title, key-takeaway bullets and recommendation
into tighter, exec-grade language, **reusing only the numbers it is given** (the
deterministic takeaways/evidence). Every rewritten field is passed through the
faithfulness verifier before it is applied; anything that introduces an unsupported
number or names an individual peer is discarded and the deterministic text stands.

No key configured → `enhance_deck` returns the deck unchanged.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from studio.ai.client import llm_available, structured
from studio.ai.models import DeckStory
from studio.ai.verifier import allowed_numbers, verify_bullets, verify_text
from studio.deck.model import DeckSpec, SlideSpec

logger = get_logger(__name__)

_CONTENT_LAYOUTS = {"insight", "decision", "exec"}

_SYSTEM = """You are an insurance QBR editor. You are given slides that already carry
correct numbers in their takeaways and evidence. Rewrite each slide's action title,
2-4 key-takeaway bullets and one recommendation to be sharper and more executive.

HARD RULES:
- Use ONLY numbers that already appear in the slide you are given. NEVER invent,
  round differently, or compute a new number.
- NEVER name an individual peer/carrier. Refer to peers only in aggregate. Naming
  Marsh is fine.
- Action title = the single most important takeaway as a sentence. Bullets = crisp
  'so what' messages. Recommendation = one imperative ('Defend…', 'Scale…', 'Enter…').
- No preamble, no hedging, no filler."""


def _tone_for(text: str) -> str:
    low = text.lower()
    if any(w in low for w in ("declin", "down", "erosion", "risk", "at risk", "soft", "below")):
        return "danger"
    if any(w in low for w in ("whitespace", "opportunity", "unwritten", "gap", "watch")):
        return "warn"
    if any(w in low for w in ("grew", "growth", "up ", "strong", "lead", "ahead", "+")):
        return "good"
    return "neutral"


def _option_name(option: Any) -> str:
    """One carrier name out of a filter option.

    ``cached_filter_options`` returns Dash option dicts (``{"label": …, "value": …}``), not
    bare strings — its signature says ``List[Dict[str, Any]]``. Reading them as strings
    raised ``'dict' object has no attribute 'lower'`` on the very first carrier, which took
    the whole of :func:`enhance_deck` down with it: the AI story pass never ran, and the
    confidentiality list it exists to enforce was never applied.
    """
    if isinstance(option, dict):
        return str(option.get("value") or option.get("label") or "").strip()
    return str(option or "").strip()


def _forbidden_names(result: Any, subject: Optional[str]) -> List[str]:
    """Every carrier but the subject and Marsh — the names AI prose may not print."""
    try:
        from studio.data import cached_filter_options

        carriers = cached_filter_options(getattr(result, "flow", "gpr")).get("Carrier_Group", [])
    except Exception:  # noqa: BLE001 — confidentiality list is best-effort
        carriers = []
    subj = (subject or "").strip().lower()
    names = (_option_name(c) for c in carriers)
    return [n for n in names if n and n.lower() not in {subj, "marsh"}]


def _slide_sources(s: SlideSpec) -> str:
    parts = [s.title, s.recommendation]
    parts += [t.get("text", "") for t in s.takeaways]
    parts += [f"{e.get('label', '')} {e.get('value', '')} {e.get('detail', '')}" for e in s.evidence]
    return " ".join(p for p in parts if p)


def _payload(content: List[Tuple[int, SlideSpec]]) -> str:
    items = [
        {
            "idx": i,
            "eyebrow": s.eyebrow,
            "current_title": s.title,
            "takeaways": [t.get("text", "") for t in s.takeaways],
            "evidence": [f"{e.get('label', '')}: {e.get('value', '')}" for e in s.evidence],
            "current_recommendation": s.recommendation,
        }
        for i, s in content
    ]
    return "Rewrite these slides. Return one entry per idx.\n" + json.dumps(items, ensure_ascii=False)


def enhance_deck(deck: DeckSpec, result: Any, *, subject: Optional[str] = None) -> DeckSpec:
    """Return a deck with verifier-checked AI prose, or the input deck unchanged."""
    if not llm_available():
        return deck
    content = [(i, s) for i, s in enumerate(deck.slides) if s.layout in _CONTENT_LAYOUTS]
    if not content:
        return deck

    story = structured(DeckStory, _SYSTEM, _payload(content), tier="reason", node="story")
    if story is None:
        return deck

    forbidden = _forbidden_names(result, subject or deck.meta.get("carrier"))
    by_idx = {sl.idx: sl for sl in story.slides}
    slides = list(deck.slides)
    rewritten = 0

    for i, s in content:
        sl = by_idx.get(i)
        if sl is None:
            continue
        allowed = allowed_numbers(_slide_sources(s))
        updates: Dict[str, Any] = {}

        title, _ = verify_text(sl.action_title, allowed, forbidden_names=forbidden)
        if title.strip():
            updates["title"] = title
        reco, _ = verify_text(sl.recommendation, allowed, forbidden_names=forbidden)
        if reco.strip():
            updates["recommendation"] = reco
        bullets, _ = verify_bullets(sl.takeaways, allowed, forbidden_names=forbidden)
        if bullets:
            updates["takeaways"] = tuple({"text": b, "tone": _tone_for(b)} for b in bullets[:4])

        if updates:
            slides[i] = replace(s, **updates)
            rewritten += 1

    logger.info("studio.ai story rewrote %d/%d content slides", rewritten, len(content))
    return replace(deck, slides=tuple(slides))
