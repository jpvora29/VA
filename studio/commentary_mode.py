"""Choose how Studio authors and verifies QBR commentary.

COMMENTARY_MODE=ai_required (default): verified AI in every requested field, or fail.
COMMENTARY_MODE=auto: explicitly permit a deterministic fallback after an AI failure.
COMMENTARY_MODE=off: deterministic preview; no model calls.
STUDIO_AI=off takes precedence. Every AI mode writes from facts, not fallback prose.
"""
from __future__ import annotations

import os
from typing import Optional

from logger import get_logger

logger = get_logger(__name__)

AI_REQUIRED = "ai_required"
AUTO = "auto"
OFF = "off"

_MODES = (AI_REQUIRED, AUTO, OFF)

#: Spellings of ``ai_required`` that a person actually types.
_ALIASES = {
    "ai": AI_REQUIRED,
    "ai-required": AI_REQUIRED,
    "required": AI_REQUIRED,
    "strict": AI_REQUIRED,
    "deterministic": OFF,
    "rules": OFF,
}


class CommentaryUnavailable(RuntimeError):
    """``ai_required`` was asked for and a model could not deliver it.

    Carries ``retryable`` because the two cases want different words in front of the user:
    a rate limit or a timed-out endpoint is "try again", and a missing deployment name is
    "fix the configuration" — and a UI that says "try again" to the second one sends the
    author round a loop that cannot succeed.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def mode() -> str:
    """Resolve the mode; missing or invalid values require verified AI."""
    from studio.ai import client

    if client.disabled():                 # STUDIO_AI=off — the kill switch wins
        return OFF
    raw = (os.getenv("COMMENTARY_MODE") or AI_REQUIRED).strip().lower()
    resolved = _ALIASES.get(raw, raw)
    if resolved not in _MODES:
        logger.warning("COMMENTARY_MODE=%r is not one of %s — requiring verified AI commentary",
                       raw, ", ".join(_MODES))
        return AI_REQUIRED
    return resolved


def ai_required() -> bool:
    """True when a deterministic column is a build failure rather than a fallback."""
    return mode() == AI_REQUIRED


def show_draft_to_author() -> bool:
    """Never anchor the AI author to finished fallback prose."""
    # Finished fallback prose anchors the model to the wording it should improve.
    # Every AI mode now authors directly from the evidence and selected findings.
    return False


def preflight(tier: str = "reason") -> None:
    """Refuse the build NOW if ``ai_required`` cannot be honoured. No-op otherwise.

    Called before the analytics layer runs, which is the whole point: the alternative is
    discovering the endpoint is unreachable after half an hour of querying and filling.
    """
    if not ai_required():
        return
    from core.llm.clients import available

    if not available(tier):
        raise CommentaryUnavailable(
            "COMMENTARY_MODE=ai_required, but no model client can be built for tier "
            f"{tier!r}. Set ENDPOINT, API_KEY, VERSION and DEPLOYMENT (or "
            f"{tier.upper()}_DEPLOYMENT), or run with COMMENTARY_MODE=auto.",
            retryable=False,
        )


def refuse(reason: str, *, retryable: bool = True, detail: str = "") -> None:
    """Fail the build when ``ai_required`` is in force; log and carry on when it is not.

    The one place the "strict or best-effort" decision is made, so every refusal path in the
    writer — an unavailable model, an empty answer, a column the verifiers emptied — reports
    itself the same way and no caller has to remember the mode.
    """
    message = f"{reason}{f' ({detail})' if detail else ''}"
    if ai_required():
        raise CommentaryUnavailable(
            f"COMMENTARY_MODE=ai_required: {message}. No deterministic prose was "
            "substituted; re-run once the cause is cleared.",
            retryable=retryable,
        )
    logger.info("commentary: %s — keeping the deterministic draft", message)


def authorship(written: bool) -> str:
    """The audit label for one section: ``ai`` or ``deterministic``."""
    return "ai" if written else "deterministic"


def describe(job_label: Optional[str] = None) -> str:
    """A one-line statement of what this run will accept — for the job log."""
    return f"commentary mode={mode()}" + (f" job={job_label}" if job_label else "")
