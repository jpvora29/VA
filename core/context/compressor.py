"""Compressor layer — extractive selection only (decisions #1, #12).

v1 does **no** LLM summarization: "compression" is just bounded extractive
selection — take the top-N ranked items, drop empties. This is where a future
`LLMCompressor` (abstractive summarization of skill bodies / definitions) would
slot in behind the same `compress()` contract; for now that path is a reserved,
unimplemented interface.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from core.context.reranker import Candidate


def compress(
    ranked: Sequence[Tuple[Candidate, float]],
    *,
    top_n: Optional[int] = None,
    min_score: float = 0.0,
) -> List[Candidate]:
    """Extractive selection: keep ranked items above `min_score`, capped at top_n."""
    kept = [c for c, score in ranked if score > min_score]
    if top_n is not None:
        kept = kept[:top_n]
    return kept


class LLMCompressor:
    """Abstractive summarization seam. Interface only — NOT implemented in v1."""

    def compress(self, items: Sequence[str]) -> str:  # pragma: no cover
        raise NotImplementedError(
            "LLM compression is out of scope for ContextEngine v1 (decision #12)."
        )
