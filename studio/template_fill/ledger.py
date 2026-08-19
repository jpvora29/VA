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
from typing import List, Sequence, Set

# A claim's signature ignores what does not change the claim: casing, run of spaces, the
# trailing full stop, and the connective a composer used to join its clauses.
_SPACE_RE = re.compile(r"\s+")


def signature(line: str) -> str:
    """The identity of the claim ``line`` makes — its wording and its figures, normalised."""
    return _SPACE_RE.sub(" ", (line or "").strip().lower()).rstrip(".")


@dataclass
class ClaimLedger:
    """What the deck has already said, in the order it said it.

    Deliberately mutable and threaded explicitly through the providers that write prose
    (see :func:`studio.template_fill.assemble._premium_providers`) rather than kept in a
    module global: the ledger is per-deck state, and a global one would leak between two
    decks generated in the same process.
    """

    _seen: Set[str] = field(default_factory=set)

    def seen(self, line: str) -> bool:
        return signature(line) in self._seen

    def record(self, lines: Sequence[str]) -> None:
        self._seen.update(signature(line) for line in lines if (line or "").strip())

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
        fresh = [line for line in lines if (line or "").strip() and not self.seen(line)]
        kept = fresh if len(fresh) >= keep_at_least else list(lines)[:keep_at_least]
        kept = kept[:limit]
        self.record(kept)
        return kept
