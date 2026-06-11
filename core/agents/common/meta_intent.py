"""Conversation meta-intent detection — Phase 2 of the query contract.

Some turns are ABOUT the conversation, not a new data question: "summarize our
discussion", "what did you recommend earlier?". These must be answered from the
persisted transcript with NO new database query — re-running analysis for a
recap wastes tokens and risks contradicting the very answers being summarized.

Detection is deterministic-first, mirroring `directives.py`: tight, conversation-
referential regexes over the raw query. A hit short-circuits the graph past the
SQL/analyst routes to the transcript handler. Patterns deliberately require a
conversational anchor (we/our/earlier/before/so far/this discussion) so a fresh
analytical question ("what do you recommend for Cyber?") is never misread as a
recall request.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# "summarize our discussion", "recap this conversation", "sum up the chat so far"
_SUMMARIZE_PATTERNS = [
    re.compile(
        r"\b(?:summari[sz]e|recap|sum\s+up|wrap\s+up)\b[^.?!]{0,30}?"
        r"\b(?:discussion|conversation|chat|session|thread|talk|so\s+far)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:give|write|make)\s+(?:me\s+)?a\s+(?:quick\s+)?"
        r"(?:summary|recap|tl;?dr)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\s+have\s+we\s+(?:discussed|covered|talked\s+about|gone\s+over)\b",
        re.IGNORECASE,
    ),
]

# "what did you recommend earlier?", "what did we conclude?", "remind me what we found"
_RECALL_PATTERNS = [
    re.compile(
        r"\bwhat\s+did\s+(?:you|we)\s+"
        r"(?:recommend|suggest|conclude|decide|find|say|cover)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\s+(?:were|was)\s+(?:your|the|our)\s+"
        r"(?:recommendations?|conclusions?|findings?|decisions?|suggestions?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\s+(?:conclusions?|decisions?|recommendations?|findings?)\b"
        r"[^.?!]{0,25}?\b(?:have\s+we|did\s+we|so\s+far|reached|made)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bremind\s+me\s+(?:what|of\s+what|about\s+what)\b", re.IGNORECASE),
    re.compile(
        r"\bwhat\s+did\s+we\s+(?:talk\s+about|discuss|go\s+over|look\s+at)\b",
        re.IGNORECASE,
    ),
]


def detect_conversation_intent(query: str) -> Optional[str]:
    """Deterministic meta-intent detection on the raw user query.

    Returns "summarize_chat", "recall_previous", or None when the turn is a
    normal data question. Summarize is checked first so "recap what we
    concluded" reads as a summary rather than a narrow recall.
    """
    text = query or ""
    if any(p.search(text) for p in _SUMMARIZE_PATTERNS):
        return "summarize_chat"
    if any(p.search(text) for p in _RECALL_PATTERNS):
        return "recall_previous"
    return None


def conversation_intent_of(routing_context: Any) -> str:
    """Read `conversation_intent` off a live model or a checkpoint dict.

    Defaults to 'analyze' for missing/legacy shapes so a normal turn can never
    be silently diverted to the transcript handler.
    """
    if routing_context is None:
        return "analyze"
    value = (
        routing_context.get("conversation_intent")
        if isinstance(routing_context, dict)
        else getattr(routing_context, "conversation_intent", None)
    )
    value = str(value or "").strip().lower()
    return value or "analyze"


def is_meta_intent(routing_context: Any) -> bool:
    """True when this turn is a conversation meta-request (no new SQL)."""
    return conversation_intent_of(routing_context) in (
        "summarize_chat",
        "recall_previous",
    )
