"""LLM-tailored starter questions, derived from a user's episodic history.

When a returning user opens a fresh chat, we surface example questions shaped by
what they've actually asked (and any answers they down-voted), instead of the
static defaults. Falls back to ``[]`` (caller uses its own defaults) for new
users or on any error, and caches per user to avoid an LLM call on every render.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from core.memory.episodic import episodic_store
from logger import get_logger

logger = get_logger(__name__)

_CACHE: dict[int, tuple[float, list[str]]] = {}
_TTL_SECONDS = 600  # refresh tailored suggestions at most every 10 minutes
_MIN_HISTORY = 3  # below this, defaults are better than a thin LLM guess
_INFLIGHT: set[int] = set()
_INFLIGHT_LOCK = threading.Lock()


def _coerce_uid(user_id: Any) -> int | None:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def generate_starter_questions(user_id: Any, *, wait: bool = False) -> list[str]:
    """Up to 4 tailored example questions; ``[]`` to signal "use defaults".

    NEVER blocks the page. This used to make a model call inline, and it is
    called while the app shell is built at sign-in — so the first screen after
    "Continue" waited on an LLM round trip. Now a cold cache returns ``[]`` at
    once and a background thread fills it; the next fresh chat shows the
    tailored set. ``wait=True`` keeps the old synchronous behaviour for tests.
    """
    uid = _coerce_uid(user_id)
    if uid is None:
        return []

    cached = _CACHE.get(uid)
    if cached and (time.time() - cached[0]) < _TTL_SECONDS:
        return cached[1]
    if wait:
        return _refresh(uid)
    with _INFLIGHT_LOCK:
        if uid in _INFLIGHT:
            return cached[1] if cached else []
        _INFLIGHT.add(uid)
    threading.Thread(target=_refresh, args=(uid,), name=f"starters-{uid}", daemon=True).start()
    return cached[1] if cached else []


def _refresh(uid: int) -> list[str]:
    """Compute and cache one user's tailored starters (runs off the UI thread)."""
    try:
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
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.discard(uid)


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
