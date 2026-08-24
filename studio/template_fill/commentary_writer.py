"""Who writes a commentary column — the rules, or a model working from evidence.

Two strategies behind one callable signature, chosen by :func:`make_writer`. Business code
depends on the signature, never on which one it got, so ``STUDIO_AI=off`` is a factory
decision rather than a branch threaded through the caller.

    write: (ColumnRequest) -> tuple[str, ...]

``compose_from_rules`` is the deterministic composer set — correct by construction, and the
fallback whenever the model is unavailable or its answer is refused.

``compose_with_agent`` is the change this module exists for. The model is given the
EVIDENCE (:mod:`studio.template_fill.commentary_evidence`), the ICG DEFINITIONS of the
terms in play (:mod:`core.definitions`), and the column's own brief — then writes the
column, citing the facts behind each sentence. It is not editing prose; it is writing from
facts, which is what lets it drop a claim, fold two into one, or lead with the consequence.
What comes back is verified twice (:mod:`studio.template_fill.commentary_verify`) before it
is allowed anywhere near a slide, and the rule draft stands if it does not survive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ColumnRequest:
    """Everything needed to write one commentary column."""

    topic: str
    pack: object                     # EvidencePack — kept loose to avoid a hard import cycle
    draft: Tuple[str, ...] = ()      # the rule composers' answer: fallback AND worked example
    subject: str = ""
    style: str = "balanced"
    bullets: int = 4
    brief: str = ""                  # the column's own brief (commentary._TOPIC_BRIEF)
    voice: str = ""                  # voice + craft + shape rules shared by every column


class ColumnWriter(Protocol):
    """A commentary writer. Takes a request, returns whole sentences."""

    def __call__(self, request: ColumnRequest) -> Tuple[str, ...]:
        ...


def compose_from_rules(request: ColumnRequest) -> Tuple[str, ...]:
    """The deterministic composers' column — already correct, already readable."""
    return tuple(request.draft)


def _writer_payload(request: ColumnRequest, glossary_brief: str) -> str:
    """What the model is shown: the evidence, the definitions, and the draft to beat."""
    blocks = [f"CARRIER: {request.subject}", "", "EVIDENCE — the only facts you may use:",
              request.pack.as_brief()]
    if glossary_brief:
        blocks += ["", "ICG DEFINITIONS — use these terms exactly as defined:", glossary_brief]
    if request.draft:
        blocks += ["", "A DETERMINISTIC DRAFT of this column, for the claims it selected "
                       "and their priority order. You are not editing it — write the column "
                       "properly from the evidence:",
                   "\n".join(f"- {line}" for line in request.draft)]
    blocks += ["", f"Write at most {request.bullets} sentences for this column."]
    return "\n".join(blocks)


def _glossary_brief(request: ColumnRequest) -> str:
    """The ICG definitions for the terms this column's evidence actually uses."""
    try:
        from core.definitions import get_glossary

        return get_glossary().brief(request.pack.terms())
    except Exception as exc:  # noqa: BLE001 — definitions sharpen prose, they do not gate it
        logger.warning("commentary_writer: glossary unavailable (%s)", exc)
        return ""


def compose_with_agent(request: ColumnRequest) -> Tuple[str, ...]:
    """A model writes the column from evidence, then both verifiers rule on it.

    Returns ``()`` when the model is unavailable, answers with nothing usable, or has every
    sentence dropped — the caller then keeps the rule draft.
    """
    from studio.ai import client
    from studio.ai.models import CommentaryColumn
    from studio.template_fill import commentary_verify as V

    glossary_brief = _glossary_brief(request)
    system = "\n".join(part for part in (request.voice, request.brief) if part)
    column = client.structured(CommentaryColumn, system,
                               _writer_payload(request, glossary_brief),
                               node=f"commentary-{request.topic}")
    if column is None or not column.bullets:
        return ()
    judged = [V.Judged(text=(b.text or "").strip(), fact_ids=tuple(b.fact_ids or ()))
              for b in column.bullets if (b.text or "").strip()]
    verdict = V.verify(judged, request.pack, glossary_brief=glossary_brief,
                       node=f"commentary-{request.topic}")
    return verdict.kept


def make_writer(*, ai_enabled: Optional[bool] = None) -> ColumnWriter:
    """The writer this run should use.

    ``ai_enabled`` defaults to whatever the AI client reports, so ``STUDIO_AI=off``, a
    missing key and a dead endpoint all land on the rule composer without the caller
    knowing there was a choice.
    """
    if ai_enabled is None:
        from studio.ai import client

        ai_enabled = client.llm_available()
    return compose_with_agent if ai_enabled else compose_from_rules
