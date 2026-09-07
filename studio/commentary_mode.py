"""Who is allowed to write the commentary this run ships.

Studio has always had a deterministic composer behind every prose column, and it has always
been the fallback: no credentials, a dead endpoint, an empty answer, a verifier drop — every
one of those paths ends by returning the rule draft, per column and quietly. That is the
right behaviour for a demo and the wrong one for a deliverable, because the two outcomes are
indistinguishable on the slide. A deck can be written entirely by the rule composers and
look exactly like one a model wrote badly, which is a bad place to be standing when someone
says the commentary reads poorly.

So the run declares what it will accept:

    COMMENTARY_MODE=ai_required   a model writes every column, or the build FAILS
    COMMENTARY_MODE=auto          today's behaviour: a model writes, rules catch it (default)
    COMMENTARY_MODE=off           the rule composers write; no model is called

``ai_required`` changes four things and nothing else:

* the writer factory may not hand back the rule composer (:mod:`commentary_writer`);
* the author prompt is not shown finished deterministic prose to imitate — it gets the
  evidence, the priorities and the column's questions, and writes from those;
* a column that ends up as its draft raises :class:`CommentaryUnavailable` instead of
  shipping;
* the configuration is checked BEFORE the build spends minutes on analytics, so a missing
  API key is an actionable error in the first second rather than a deterministic deck in
  the thirtieth minute.

``STUDIO_AI=off`` still wins over everything: it is a kill switch, and a kill switch that
can be overridden is not one. Asking for both is a contradiction, and this module answers
it the safe way — off — rather than failing a run that explicitly asked for no model.
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
    """This run's commentary mode — one of ``ai_required``, ``auto``, ``off``.

    An unrecognised value reads as ``auto`` with a warning rather than raising: a typo in an
    environment variable must not stop a build, and the warning is how it gets noticed.
    """
    from studio.ai import client

    if client.disabled():                 # STUDIO_AI=off — the kill switch wins
        return OFF
    raw = (os.getenv("COMMENTARY_MODE") or AUTO).strip().lower()
    resolved = _ALIASES.get(raw, raw)
    if resolved not in _MODES:
        logger.warning("COMMENTARY_MODE=%r is not one of %s — reading it as %r",
                       raw, ", ".join(_MODES), AUTO)
        return AUTO
    return resolved


def ai_required() -> bool:
    """True when a deterministic column is a build failure rather than a fallback."""
    return mode() == AI_REQUIRED


def show_draft_to_author() -> bool:
    """Whether the author prompt may include the finished deterministic prose.

    In ``auto`` it may, and does: the draft is the claim selection and the priority order,
    and a model shown one writes a better column than a model shown a bare fact list. In
    ``ai_required`` it may not, because a model handed completed sentences reliably rewords
    them, and a reworded rule draft is a deterministic column with an ``authorship=ai``
    label on it. It still gets the evidence, the column's brief and the questions the column
    exists to answer — which is the intent the draft was standing in for.

    The cost is real and worth naming: the draft is also where the deck's
    :class:`~studio.template_fill.ledger.ClaimLedger` shows through, so withholding it gives
    up some of the cross-page de-duplication the ledger buys. Within a sub-deck nothing is
    lost — the section prompt tells the model outright that no two of its fields may make
    the same point — and the whole-deck repetition check still reports what slips through
    (:func:`studio.template_fill.commentary_qa.check_narratives`). That is the trade
    ``ai_required`` makes on purpose: genuine authorship over guaranteed non-repetition.
    """
    return not ai_required()


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
