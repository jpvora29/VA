"""Commentary contracts — what each slide type is *allowed* to say (Phase 4).

One frozen dataclass per rule set, dispatched by slide purpose (the repo's
dict-dispatch idiom). A contract bounds the drafting agent: which measures may
be cited, how many bullets/sentences fit, whether recommendations are welcome.
Caps come from ``rules.yaml`` (commentary block) so non-engineers can tune them.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Tuple

# The recommended narrative structure from the plan:
# what changed → why it matters → what drove it (if supported) → what to watch/decide.
STRUCTURE = ("what_changed", "why_it_matters", "drivers", "watch_next")


@dataclass(frozen=True)
class CommentaryContract:
    purpose: str
    allowed_measures: Tuple[str, ...]
    max_bullets: int = 3
    max_sentences_per_bullet: int = 2
    require_fact_citations: bool = True
    allow_recommendations: bool = False
    structure: Tuple[str, ...] = STRUCTURE


_ALL_MEASURES = (
    "premium_total", "premium_movement", "premium_movement_pct",
    "rank", "sow", "hhi", "concentration", "peer_ratio", "whitespace_market",
)

# Purpose → contract. Slide purposes come from the layout agent's vocabulary.
CONTRACTS: Mapping[str, CommentaryContract] = {
    "executive_summary": CommentaryContract(
        "executive_summary", _ALL_MEASURES, allow_recommendations=True),
    "trading_summary": CommentaryContract(
        "trading_summary",
        ("premium_total", "premium_movement", "premium_movement_pct", "rank", "sow")),
    "product_deep_dive": CommentaryContract(
        "product_deep_dive",
        ("premium_total", "premium_movement", "premium_movement_pct", "sow")),
    "country_view": CommentaryContract(
        "country_view",
        ("premium_total", "premium_movement", "premium_movement_pct", "rank", "sow")),
    "swot": CommentaryContract(
        "swot", _ALL_MEASURES, allow_recommendations=True),
    "growth": CommentaryContract(
        "growth", ("premium_movement", "premium_movement_pct", "premium_total")),
    "ranking": CommentaryContract(
        "ranking", ("rank", "premium_total", "peer_ratio")),
    "appendix": CommentaryContract(
        "appendix", _ALL_MEASURES, max_bullets=5),
}

_DEFAULT = CommentaryContract("other", _ALL_MEASURES)


def contract_for(purpose: str) -> CommentaryContract:
    """The contract for a slide purpose, with rules.yaml caps applied."""
    from studio.rules import load_rules

    caps = load_rules().commentary
    base = CONTRACTS.get(purpose, replace(_DEFAULT, purpose=purpose))
    return replace(
        base,
        max_bullets=min(base.max_bullets, caps.max_bullets_per_slide)
        if base.purpose != "appendix" else base.max_bullets,
        max_sentences_per_bullet=min(base.max_sentences_per_bullet, caps.max_sentences_per_bullet),
    )
