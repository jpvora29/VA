"""Claim ledger — a deck makes each claim once.

The composers in :mod:`studio.template_fill.feedback` answer their question from the facts
in scope, and several pages ask the SAME question of the SAME book: the highlights page,
the trading summary and the ranking page's "Key Highlights" all describe the whole account.
Each composed the same opening sentence, so one claim landed on four slides.

The ledger is the deck-level memory that stops it. Every page takes its lines THROUGH the
ledger: lines carrying a claim the deck has already made are dropped in favour of the
page's next-best points, and the claim is recorded so the page after it moves on again.

Two design choices keep this deterministic (no embeddings, no model call):

  * it runs on the DETERMINISTIC draft, before any LLM polish — at that layer a repeated
    claim is a repeated *string*, because it came from the same builder with the same
    figures, so exact matching on a normalised signature is exhaustive rather than
    approximate;
  * a claim's signature keeps its numbers, so two products saying "grew X% year on year"
    about their own books are different claims, while one book's figure quoted twice is
    the same claim.

A page must still say something, so :meth:`ClaimLedger.unseen` never returns fewer than
``keep_at_least`` lines — deduplication may not blank a cell that :mod:`feedback`'s
fallbacks just guaranteed would be filled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Set

# A claim's signature ignores what does not change the claim: casing, run of spaces, the
# trailing full stop, and the connective a composer used to join its clauses.
_SPACE_RE = re.compile(r"\s+")


def signature(line: str) -> str:
    """The identity of the claim ``line`` makes — its wording and its figures, normalised."""
    return _SPACE_RE.sub(" ", (line or "").strip().lower()).rstrip(".")


#: Figures, so a sentence's SHAPE can be compared without them.
_FIGURE_RE = re.compile(r"\d[\d,]*\.?\d*")

#: Proper nouns AFTER the first word — the product, country or industry a page is
#: about. Masked for the shape comparison and only there: "Property" and "Casualty"
#: are what make two otherwise identical sentences look like two findings. The
#: first word is left alone so an ordinary sentence-initial "The" is not treated
#: as an entity.
_ENTITY_RE = re.compile(r"(?<=\w[\s,;:—-])\b[A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*)*")

#: How many times one sentence shape may be used across a deck before it gives way
#: to a page's next-best point. Two, not one: a shape used twice in a ten-product
#: deck is a house style, and the same shape on every page is a template.
MAX_SHAPE_USES = 2


def shape(line: str) -> str:
    """The sentence PATTERN ``line`` follows, with its figures masked out.

    ``signature`` keeps the numbers, deliberately — two products saying "grew X%"
    about their own books are making two different claims, and suppressing the
    second would delete a true finding. But it means a ten-product deck ships ten
    sentences built from one mould, which is exactly what a reader means by "lots
    of repetition even when 8-10 products are included": every claim is new and
    every page reads the same.

    So the ledger tracks both. A repeated claim is dropped outright; a repeated
    SHAPE is allowed a couple of outings and then has to give way, which promotes
    the page's next-best point rather than blanking the column.

    Both the figures and the ENTITY are masked, because both are what a template
    varies: "the book grew 12% and that growth sits in Property" and "...8% ... in
    Casualty" are the same sentence twice, and masking only the numbers leaves the
    product name to tell them apart.
    """
    masked = _ENTITY_RE.sub("@", (line or "").strip())
    return _FIGURE_RE.sub("#", signature(masked))


@dataclass
class ClaimLedger:
    """What the deck has already said, in the order it said it.

    Deliberately mutable and threaded explicitly through the providers that write prose
    (see :func:`studio.template_fill.assemble._premium_providers`) rather than kept in a
    module global: the ledger is per-deck state, and a global one would leak between two
    decks generated in the same process.
    """

    _seen: Set[str] = field(default_factory=set)
    #: sentence shape -> how many pages have used it (see :func:`shape`).
    _shapes: Dict[str, int] = field(default_factory=dict)

    def seen(self, line: str) -> bool:
        return signature(line) in self._seen

    def overused(self, line: str) -> bool:
        """True when this sentence's SHAPE has had its outings already."""
        return self._shapes.get(shape(line), 0) >= MAX_SHAPE_USES

    def record(self, lines: Sequence[str]) -> None:
        for line in lines:
            if not (line or "").strip():
                continue
            self._seen.add(signature(line))
            key = shape(line)
            self._shapes[key] = self._shapes.get(key, 0) + 1

    def take(self, lines: Sequence[str], *, limit: int, keep_at_least: int = 1) -> List[str]:
        """The first ``limit`` of ``lines`` making a claim the deck has not made yet.

        Dropping a used claim BEFORE the trim is the point: it promotes the page's
        next-best point into the space, so a page that loses its opening line still fills
        its column rather than shrinking by one.

        Falls back to the first ``keep_at_least`` of the original lines when every one of
        them has been said before — a page repeating a claim reads better than a page with
        an empty column, and the caller has no other text to offer.

        Only the lines that actually ship are recorded; a point trimmed off the end has not
        been said, and the page after this one may still say it.
        """
        usable = [line for line in lines if (line or "").strip() and not self.seen(line)]
        # Prefer the lines whose SHAPE the deck has not worn out, but keep the rest
        # in order behind them rather than discarding: a page must still fill its
        # column, and a repeated shape beats an empty one.
        fresh = [line for line in usable if not self.overused(line)]
        ranked = fresh + [line for line in usable if line not in fresh]
        kept = ranked if len(ranked) >= keep_at_least else list(lines)[:keep_at_least]
        kept = kept[:limit]
        self.record(kept)
        return kept
