"""LLM-tailored starter questions, derived from a user's episodic history.

When a returning user opens a fresh chat, we surface example questions shaped by
what they've actually asked (and any answers they down-voted), instead of the
static defaults. Falls back to ``[]`` (caller uses its own defaults) for new
users or on any error, and caches per user to avoid an LLM call on every render.
"""
from __future__ import annotations

import json
import time
from typing import Any

from core.memory.episodic import episodic_store
from logger import get_logger

logger = get_logger(__name__)

_CACHE: dict[int, tuple[float, list[str]]] = {}
_TTL_SECONDS = 600  # refresh tailored suggestions at most every 10 minutes
_MIN_HISTORY = 3  # below this, defaults are better than a thin LLM guess


def _coerce_uid(user_id: Any) -> int | None:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def generate_starter_questions(user_id: Any) -> list[str]:
    """Up to 4 tailored example questions; ``[]`` to signal "use defaults"."""
    uid = _coerce_uid(user_id)
    if uid is None:
        return []

    cached = _CACHE.get(uid)
    if cached and (time.time() - cached[0]) < _TTL_SECONDS:
        return cached[1]

    questions = episodic_store.recent_questions(uid, limit=25)
    if len(questions) < _MIN_HISTORY:
        _CACHE[uid] = (time.time(), [])
        return []

    disliked = [
        f.get("content")
        for f in episodic_store.recent_feedback(uid, limit=15)
        if f.get("rating") == "down" and f.get("content")
    ]

    try:
        tailored = _ask_llm(questions, disliked)
    except Exception:  # pragma: no cover - never break the welcome screen
        logger.exception("generate_starter_questions LLM call failed")
        tailored = []

    _CACHE[uid] = (time.time(), tailored)
    return tailored


def invalidate(user_id: Any) -> None:
    """Drop a user's cached suggestions (e.g. after meaningful new activity)."""
    uid = _coerce_uid(user_id)
    if uid is not None:
        _CACHE.pop(uid, None)


def _ask_llm(history: list[str], disliked: list[str]) -> list[str]:
    # Imported lazily so this module stays importable without the LLM/env layer.
    from langchain_core.messages import HumanMessage, SystemMessage

    from core.initialization import Initialization

    system = (
        "You are helping an insurance analytics assistant suggest example questions. "
        "Given a user's recent questions, propose 4 fresh, concise example questions "
        "that the same user is likely to find useful next. Stay strictly within the "
        "domain of the prior questions (premium, Share of Wallet, broker sentiment, "
        "peer benchmarks, market rates, carriers, countries, product lines). Each "
        "question must be self-contained, specific, and under 16 words. Do NOT repeat "
        "a prior question verbatim. Return ONLY a JSON array of 4 strings."
    )
    human = "Recent questions:\n- " + "\n- ".join(history[:25])
    if disliked:
        human += "\n\nAvoid styles similar to these down-voted answers:\n- " + "\n- ".join(
            d for d in disliked[:10]
        )

    response = Initialization.llm_creative.invoke(
        [SystemMessage(content=system), HumanMessage(content=human)]
    )
    return _parse_questions(getattr(response, "content", "") or "")


def _parse_questions(text: str) -> list[str]:
    text = text.strip()
    # Tolerate code fences / stray prose around the JSON array.
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    out = [str(q).strip() for q in data if isinstance(q, (str,)) and str(q).strip()]
    return out[:4]
