"""What went wrong with an answer — the vocabulary a thumbs-down is graded on.

A bare thumbs-down records that an answer failed and nothing about how, which is
the only part anyone can act on. "Wrong period" and "confusing explanation" are
different defects with different fixes: one is a filter bug worth a regression
test, the other is a prompt problem. Stored as a single `rating` column they are
indistinguishable, so the signal accumulates and is never usable.

This module is the shared vocabulary. The chat UI renders these as the chips
shown under a downvote; :meth:`~core.memory.episodic.SqliteEpisodicStore.record_feedback`
stores the chosen key; `feeds` records what an approved correction should
eventually contribute to, so the review queue knows where each kind of failure
goes rather than piling every complaint into one list.

Pure data and pure functions — no DB, no Dash — so both sides can import it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class FeedbackReason:
    """One way an answer can be wrong, as the user would say it."""

    key: str
    label: str
    icon: str
    #: What an approved correction of this kind contributes to. Descriptive for
    #: now — the review queue reads it; nothing is auto-applied, because a
    #: business rule learned from an unreviewed downvote is a business rule
    #: nobody agreed to.
    feeds: str


#: Display order is deliberate: the three scope/metric/period defects come first
#: because they are both the most common and the most diagnosable.
REASONS: Tuple[FeedbackReason, ...] = (
    FeedbackReason(
        "wrong_scope",
        "Wrong scope",
        "bi bi-crosshair",
        "filter resolution + regression tests",
    ),
    FeedbackReason(
        "wrong_metric",
        "Wrong metric",
        "bi bi-rulers",
        "terminology mappings + metric definitions",
    ),
    FeedbackReason(
        "wrong_period",
        "Wrong period",
        "bi bi-calendar3",
        "timeframe resolution + regression tests",
    ),
    FeedbackReason(
        "bad_evidence",
        "Numbers look wrong",
        "bi bi-exclamation-diamond",
        "analytics primitives + regression tests",
    ),
    FeedbackReason(
        "confusing",
        "Hard to follow",
        "bi bi-chat-square-text",
        "answer shape + writing contract",
    ),
    FeedbackReason(
        "bad_chart",
        "Wrong chart",
        "bi bi-bar-chart-line",
        "chart selection rules",
    ),
    FeedbackReason(
        "missing_context",
        "Missing context",
        "bi bi-puzzle",
        "analysis lenses + verified answers",
    ),
    FeedbackReason(
        "other",
        "Something else",
        "bi bi-three-dots",
        "review queue",
    ),
)

_BY_KEY: Dict[str, FeedbackReason] = {reason.key: reason for reason in REASONS}

#: The keys the store accepts. Anything else is dropped rather than persisted.
REASON_KEYS: Tuple[str, ...] = tuple(_BY_KEY)

#: The reason that always wants the user's own words rather than a chip alone.
FREE_TEXT_REASON = "other"


def get_reason(key: Optional[str]) -> Optional[FeedbackReason]:
    """The reason for a key, or None when it is unknown/absent."""
    return _BY_KEY.get((key or "").strip().lower())


def reason_label(key: Optional[str]) -> str:
    """Human-readable label for a key; the raw key when it is not one of ours."""
    reason = get_reason(key)
    return reason.label if reason else (key or "")


def is_valid(key: Optional[str]) -> bool:
    return get_reason(key) is not None
