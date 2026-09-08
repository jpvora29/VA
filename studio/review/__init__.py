"""Review — why the deck on screen is not finished, in the author's terms.

    model        the report, as dataclasses (no Dash, no formatting)
    causes       the vocabulary of reasons, each with its mechanism and its fix
    capability   what the run's data can and cannot support, probed from the values
    slots        every placeholder that will not carry data, and which cause owns it
    commentary   which prose boxes were written, and what the writing lost
    report       the builder that assembles all of it

The one entry point is :func:`build_review_report`, which takes the filled TemplateDoc
already on screen and returns a :class:`~studio.review.model.ReviewReport`. It is pure
and cheap — one pass over the manifest, no engine, no LLM — so the Review tab can
recompute it on every render and can never describe a different deck from the one being
previewed.
"""
from studio.review.capability import cause_for_role, probe
from studio.review.causes import CAUSES, cause
from studio.review.commentary import diagnose_commentary, lost_claim_families
from studio.review.model import (
    Capability,
    Cause,
    CauseGroup,
    CommentaryFinding,
    ReviewReport,
    SlotFinding,
)
from studio.review.report import ReviewReportBuilder, build_review_report
from studio.review.slots import diagnose_slots

__all__ = [
    "build_review_report", "ReviewReportBuilder", "ReviewReport",
    "Cause", "Capability", "CauseGroup", "CommentaryFinding", "SlotFinding",
    "CAUSES", "cause", "cause_for_role", "probe",
    "diagnose_slots", "diagnose_commentary", "lost_claim_families",
]
