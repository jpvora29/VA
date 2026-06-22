"""Narration layer — deterministic (rule-based) now; LLM narrator + faithfulness
verifier later (DESIGN.md §2, build step 6)."""
from __future__ import annotations

from studio.narrate.commentary import (
    breakdown_takeaways,
    build_commentary,
    build_initiatives,
    build_swot,
    whitespace_takeaways,
)

__all__ = [
    "build_commentary",
    "breakdown_takeaways",
    "whitespace_takeaways",
    "build_swot",
    "build_initiatives",
]
