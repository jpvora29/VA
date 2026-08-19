"""Strategic posture — the one deliberate stance a book is in, derived from its figures.

A QBR that reports six products and recommends "grow" on all six has not advised anybody.
This module turns the premium facts already on the page into ONE posture per book, chosen
by explicit thresholds rather than written by a model, so the same figures always produce
the same call and the call can be checked.

    Defend             a leading position, held — the risk is losing it
    Scale              share and rank improving together, with room left
    Fix                growing slower than the pool, or giving share back
    Selectively pursue broadly tracking the pool, no position change to argue from
    Validate           a pool the carrier barely writes — see :mod:`studio.opportunity`

Deliberately five, not six. A sixth ("deprioritise") asks whether a book has a credible
pathway, and premium data cannot answer that: it shows what was written, never what could
have been. Adding it would mean inventing the judgement the posture exists to make
honestly, so it waits for the appetite and capacity inputs that would support it.

Order is the whole design: Validate before Fix (a book that is barely written has nothing
to fix yet), Defend before Scale (a leader's first job is holding the lead, even when it
is also growing fast), and Selectively pursue last, as the honest "nothing to argue" case.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Tuple

# ── thresholds (every one of them named, so a reviewer can argue with it) ────

# A book holding less than this share of its own Marsh pool is not a position — it is a
# pool the carrier is absent from, whatever the premium reads.
UNWRITTEN_SHARE = 0.01
# #1-#2 is the lead the deck's own band split calls a position to defend.
LEAD_RANK = 2
# A share move worth calling repeatable rather than drift.
MATERIAL_SHARE_MOVE = 1.0          # percentage points
# How far above the pool's growth a book must run before "scale" is a finding rather than
# a rounding difference. Two points of outperformance is noise; five is a trend.
SCALE_GROWTH_MARGIN = 5.0          # percentage points


class Posture(str, Enum):
    DEFEND = "Defend"
    SCALE = "Scale"
    FIX = "Fix"
    SELECTIVE = "Selectively pursue"
    VALIDATE = "Validate"


@dataclass(frozen=True)
class PostureInput:
    """What a posture is decided from — every field optional but ``name``.

    Assembled from whatever the caller already has: a product page has the full fact set,
    the overall page has one breakdown row per product. A missing field never invents a
    posture, it only narrows which ones can be reached.
    """

    name: str
    premium: Optional[float] = None
    pool: Optional[float] = None            # the Marsh premium in the same scope
    growth_pct: Optional[float] = None      # the carrier's YoY
    pool_growth_pct: Optional[float] = None # the Marsh book's YoY, same scope
    rank: Optional[int] = None
    rank_change: Optional[int] = None       # + = moved up
    share: Optional[float] = None           # share of wallet, %
    share_change: Optional[float] = None    # percentage points
    peer_share: Optional[float] = None      # top-5 peer average share, %
    behind_peer: Optional[float] = None     # own premium − top-5 average (− = behind)


@dataclass(frozen=True)
class PostureCall:
    """The posture and the one figure-bearing clause that justifies it."""

    posture: Posture
    because: str

    @property
    def verb(self) -> str:
        return self.posture.value


# ── the tests, in precedence order ───────────────────────────────────────────
# Each returns the justifying clause when it holds, else None. They read in the order the
# module docstring gives, and the first that holds decides.


def _barely_written(x: PostureInput) -> Optional[str]:
    if not x.pool or x.premium is None:
        return None
    if x.premium > x.pool * UNWRITTEN_SHARE:
        return None
    return "the carrier writes effectively none of the Marsh premium placed here"


def _losing_ground(x: PostureInput) -> Optional[str]:
    if x.growth_pct is None or x.pool_growth_pct is None:
        return None
    if x.growth_pct >= x.pool_growth_pct:
        return None
    shrinking = x.growth_pct < 0
    giving_back = (x.share_change or 0) < 0
    if not (shrinking or giving_back):
        return None
    moved = "fell" if shrinking else "grew"
    return (f"the book {moved} {abs(x.growth_pct):.1f}% against a Marsh book that grew "
            f"{x.pool_growth_pct:.1f}%")


def _holds_a_lead(x: PostureInput) -> Optional[str]:
    if (x.growth_pct or 0) < 0:
        return None                                    # a shrinking book is not defending
    leads_on_rank = x.rank is not None and x.rank <= LEAD_RANK
    leads_on_share = (
        (x.peer_share is not None and x.share is not None and x.share >= x.peer_share)
        or (x.behind_peer is not None and x.behind_peer >= 0)
    )
    if not (leads_on_rank or leads_on_share):
        return None
    if leads_on_rank:
        return f"the book ranks #{int(x.rank)} in the Marsh book"
    return "the book writes more than the top-5 peer average"


def _winning_share(x: PostureInput) -> Optional[str]:
    on_share = (x.share_change or 0) >= MATERIAL_SHARE_MOVE
    outgrowing = (
        x.growth_pct is not None and x.pool_growth_pct is not None
        and x.growth_pct - x.pool_growth_pct >= SCALE_GROWTH_MARGIN
        and (x.rank_change or 0) >= 1
    )
    if not (on_share or outgrowing):
        return None
    if on_share and x.share is not None:
        return f"share of wallet rose {x.share_change:.1f}pp to {x.share:.1f}%"
    return (f"the book grew {x.growth_pct:.1f}% against a Marsh book that grew "
            f"{x.pool_growth_pct:.1f}%, and the rank moved with it")


def _tracking(x: PostureInput) -> Optional[str]:
    """The honest "nothing to argue from" case — still said with a figure behind it.

    Leads on SHARE rather than on growth: a growth-versus-pool clause here would make the
    same claim the portfolio's movement lines already make, and the ledger only catches
    repetition it can see in the words.
    """
    if x.growth_pct is None:
        return None
    if x.share is not None:
        return (f"the book holds {x.share:.1f}% of the wallet and is neither gaining nor "
                f"losing it materially")
    return f"the book grew {x.growth_pct:.1f}%, broadly with its pool"


_TESTS: Tuple[Tuple[Posture, Callable[[PostureInput], Optional[str]]], ...] = (
    (Posture.VALIDATE, _barely_written),
    (Posture.FIX, _losing_ground),
    (Posture.DEFEND, _holds_a_lead),
    (Posture.SCALE, _winning_share),
    (Posture.SELECTIVE, _tracking),
)


def posture_for(x: PostureInput) -> Optional[PostureCall]:
    """The one posture ``x``'s figures support, or ``None`` when they support none."""
    for posture, test in _TESTS:
        because = test(x)
        if because:
            return PostureCall(posture, because)
    return None


# Posture → how it is SAID in a sentence. Kept beside the enum so a new stance cannot be
# added without deciding how it reads aloud.
_CALL_PHRASE = {
    Posture.DEFEND: "defend the position",
    Posture.SCALE: "scale this book",
    Posture.FIX: "fix this book",
    Posture.SELECTIVE: "pursue this book selectively",
    Posture.VALIDATE: "validate before committing capacity",
}


def call_phrase(posture: Posture) -> str:
    """The stance as an imperative that can sit inside a sentence."""
    return _CALL_PHRASE[posture]


def sentence(call: PostureCall, name: str) -> str:
    """The posture as a line for a slide — the stance, then why."""
    return f"{call.verb} {name}: {call.because}."
