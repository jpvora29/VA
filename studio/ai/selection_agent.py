"""Slide-selection agent — which findings make the deck, and in what priority.

Given the candidate findings (with materiality) plus the audience and meeting
length, returns the ordered set of agenda-section ids to INCLUDE — so an executive
30-minute review yields a tighter deck than a full QBR. Deterministic fallback:
return None and the planner keeps every material finding in canonical order.
"""
from __future__ import annotations

import json
from typing import Any, List, Optional

from logger import get_logger
from studio.ai.client import llm_available, structured
from studio.ai.models import SectionOrder

logger = get_logger(__name__)

_SYSTEM = """You are a QBR editor deciding which sections a deck should contain for a
given audience and meeting length. Return ONLY section ids from the provided
candidates, ordered most-important first. Drop low-materiality sections for short or
executive meetings; keep the full set for a detailed review. Never invent ids."""


def select_sections(
    spec: Any, *, audience: str = "executive", meeting_length: str = "standard"
) -> Optional[List[str]]:
    """Ordered include-list of section ids, or None to keep the deterministic plan."""
    if not llm_available():
        return None
    candidates = [
        {"section": f.section, "title": f.action_title, "materiality": round(float(f.materiality or 0), 2)}
        for f in getattr(spec, "findings", [])
    ]
    if not candidates:
        return None
    payload = json.dumps(
        {"audience": audience, "meeting_length": meeting_length, "candidates": candidates},
        ensure_ascii=False,
    )
    result = structured(SectionOrder, _SYSTEM, payload, node="selection")
    if result is None or not result.sections:
        return None
    valid = {c["section"] for c in candidates}
    chosen = [s for s in result.sections if s in valid]
    logger.info("studio.ai selection kept %d/%d sections", len(chosen), len(candidates))
    return chosen or None
