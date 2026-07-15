"""Evidence-grounded commentary: contracts → planner → drafting agent → verifier.

Implements Phases 4–5 of the QBR Studio Template Intelligence plan. Every
sentence cites fact ids; the deterministic verifier is the authority.
"""
from __future__ import annotations

from studio.commentary.agent import (
    SlideCommentary,
    draft_and_verify_commentary,
    draft_deterministic,
    draft_slide_commentary,
)
from studio.commentary.contracts import CommentaryContract, contract_for
from studio.commentary.planner import (
    CommentaryPlan,
    SlideCommentaryPlan,
    build_commentary_plan,
)
from studio.commentary.verify import (
    CommentarySentence,
    VerificationIssue,
    verify_sentences,
)

__all__ = [
    "CommentaryContract", "contract_for",
    "CommentaryPlan", "SlideCommentaryPlan", "build_commentary_plan",
    "CommentarySentence", "VerificationIssue", "verify_sentences",
    "SlideCommentary", "draft_deterministic", "draft_slide_commentary",
    "draft_and_verify_commentary",
]
