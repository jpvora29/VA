"""Reranker layer — deterministic weighted ordering (decision #1).

v1 does **no** model rerank (decision #12): ordering is a transparent weighted
score over signals the registry already provides — does the candidate's column
appear in the query, is it an entity vs a measure, did it resolve to a concrete
value. The `ModelReranker` interface is reserved but deliberately unimplemented.

Kept small and pure so a future model rerank slots in behind the same `rank()`
contract without disturbing the engine wiring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

# Default signal weights — resolved-to-a-value beats mentioned-column beats role.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "resolved": 3.0,
    "query_mention": 2.0,
    "entity_role": 1.0,
}


@dataclass(frozen=True)
class Candidate:
    """A rankable context item (e.g. a column to surface)."""

    key: str
    role: str = ""
    resolved: bool = False


def rank(
    candidates: Sequence[Candidate],
    query: str,
    *,
    weights: Dict[str, float] = DEFAULT_WEIGHTS,
) -> List[Tuple[Candidate, float]]:
    """Deterministic descending-score ordering. Stable on ties (by key)."""
    query_lower = (query or "").lower()
    scored: List[Tuple[Candidate, float]] = []
    for c in candidates:
        score = 0.0
        if c.resolved:
            score += weights.get("resolved", 0.0)
        if c.key.lower() in query_lower:
            score += weights.get("query_mention", 0.0)
        if c.role == "entity":
            score += weights.get("entity_role", 0.0)
        scored.append((c, score))
    scored.sort(key=lambda item: (-item[1], item[0].key))
    return scored


class ModelReranker:
    """Cross-encoder / LLM rerank seam. Interface only — NOT implemented in v1."""

    def rank(self, candidates: Sequence[Candidate], query: str):  # pragma: no cover
        raise NotImplementedError(
            "Model rerank is out of scope for ContextEngine v1 (decision #12)."
        )
