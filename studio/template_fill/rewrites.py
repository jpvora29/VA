"""Deferred commentary rewrites — write a deck's columns together, not page by page.

Every prose column in the deck is written by a model from the same evidence, and each of
those writes is a network wait of a few seconds followed by a verifier that is another
one. Done where the column is composed, they run strictly one after the next: measured on
a six-product, four-country deck that is 93 columns and about 190 model calls in a single
file, and it is the whole reason a build took hours rather than minutes.

Nothing about them is sequential, though. A column is written from ITS OWN facts and its
own brief; what stops two of them repeating each other is the
:class:`~studio.template_fill.ledger.ClaimLedger`, which has already run by the time a
column reaches a model. So this module splits the composing from the writing:

    compose (ordered, deterministic)  ->  PendingRewrite in the values
    write   (concurrent, any order)   ->  the finished text in its place

A :class:`PendingRewrite` is not a promise or a future — it is the finished deterministic
draft plus what a model would need to improve on it. A value holding one is already
correct and already renderable, which is what makes the deferral safe: if the writing step
never runs, or a model is unavailable, the deck ships the draft. Output cannot depend on
which column finished first, because each is written back to the role it came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PendingRewrite:
    """One commentary column a model has yet to write, standing in for its text.

    ``draft`` is the deterministic composers' answer — the fallback AND the worked
    example the model is shown. The rest is the column's brief: which topic it answers,
    for whom, in what voice, and from which facts.
    """

    draft: str
    node: str
    topic: str = ""
    subject: str = ""
    style: str = "balanced"
    facts: Dict[str, Any] = field(default_factory=dict, compare=False)

    def __str__(self) -> str:
        """The draft — so a pending that is never written still renders as prose."""
        return self.draft


ColumnWriter = Callable[[PendingRewrite], str]


def pending_items(values: Mapping[str, Any]) -> List[Tuple[str, PendingRewrite]]:
    """The ``(role, pending)`` pairs in one value set, in the set's own order."""
    return [(role, val) for role, val in values.items() if isinstance(val, PendingRewrite)]


def _written(values: Mapping[str, Any], text_by_role: Mapping[str, str]) -> Dict[str, Any]:
    """``values`` with each pending replaced by what the writer produced for its role."""
    return {role: text_by_role.get(role, val) if isinstance(val, PendingRewrite) else val
            for role, val in values.items()}


def write_all(value_sets: Sequence[Mapping[str, Any]], write: Optional[ColumnWriter] = None,
              ) -> List[Dict[str, Any]]:
    """Every pending column across every value set, written concurrently.

    The unit of concurrency is deliberately the WHOLE deck rather than one page or one
    sub-deck: a country block has four columns and a pool sized for four would spend the
    build idle. Results are written back by role, so a value set comes out in the order
    it went in whatever order the models answered.

    ``write`` defaults to the real model writer; passing one is how a test drives this
    without a model, and how the caller stays testable without one.
    """
    from studio.parallel import gather_list
    from studio.template_fill.commentary import write_column

    write = write or write_column
    indexed = [(i, role, pending)
               for i, values in enumerate(value_sets)
               for role, pending in pending_items(values)]
    if not indexed:
        return [dict(values) for values in value_sets]

    logger.info("rewrites: writing %d commentary column(s) across %d value set(s)",
                len(indexed), len(value_sets))
    texts = gather_list([lambda p=item: write(p) for _, _, item in indexed])

    by_set: List[Dict[str, str]] = [{} for _ in value_sets]
    for (i, role, pending), text in zip(indexed, texts):
        by_set[i][role] = text if text else pending.draft
    _log_authorship(indexed, texts)
    return [_written(values, by_set[i]) for i, values in enumerate(value_sets)]


def _log_authorship(indexed: Sequence[Tuple[int, str, PendingRewrite]],
                    texts: Sequence[str]) -> None:
    """Report how much of this deck a model actually wrote.

    Every refusal path in the writer — no credentials, a dead endpoint, an empty answer,
    a verifier drop, a shape the ``_accept`` gate refuses — ends by returning the
    deterministic draft, and does it per column and quietly. So a deck could be written
    entirely by the rule composers and look exactly like one the model wrote badly, which
    is a bad place to be standing when someone says the commentary reads poorly. A column
    whose text is still its draft was not written by the model, whatever the reason.
    """
    written = sum(1 for item, text in zip(indexed, texts) if text and text != item[2].draft)
    total = len(indexed)
    logger.info("commentary authorship: %d/%d column(s) written by the model, %d kept the "
                "deterministic draft", written, total, total - written)
    if total and not written:
        logger.warning("commentary authorship: NO column in this deck was model-written — "
                       "every one fell back to its deterministic draft. Check STUDIO_AI, "
                       "the LLM credentials, and the verifier logs above.")


def write_now(values: Mapping[str, Any]) -> Dict[str, Any]:
    """One value set's pending columns, written on the spot.

    For the callers that own a single page — the on-screen template document, a test —
    where there is no deck to batch across.
    """
    return write_all([values])[0]
