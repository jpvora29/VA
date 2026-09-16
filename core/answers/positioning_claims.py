"""Turning a position into a sentence worth reading.

The existing claim library describes MOVEMENT well — what grew, what fell, what
offset what. What it could never say is where the carrier actually stands, because
nothing gathered the numbers that answer it. A reader given "Property premium was
$900k, down $300k" has been told a fact and left to do the analysis themselves.

These claims say the other half:

    scale        how big this line is inside the carrier's own book
    penetration  how much of Marsh's book in that line the carrier holds
    standing     where that puts it against the other carriers in the slice
    headroom     what the rest of the book is, as an observation

The rule that makes them insight rather than decoration: a claim is only emitted
when the numbers behind it are actually interesting. "Property is 62% of the book
and holds 51% of the wallet" earns its place; "Casualty is 25% of the book" on its
own does not, and a list of every slice's share is the number-stating the reader
already complained about. `_notable` is where that judgement lives, and it is
deliberately the only judgement in the module — everything else is arithmetic
that happened upstream.

Every sentence is built by code from figures a primitive computed, so the writer
can reword but never re-derive. Same contract as the rest of `core.answers`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from core.analytics.positioning import PositioningPack, SlicePosition
from core.answers.claims import AnswerClaim
from core.answers.facts import AnswerFact, format_value, stable_id

#: A line holding this much of the carrier's own book is a concentration worth
#: naming rather than a line among many.
CONCENTRATED = 40.0

#: Share of wallet at or above this is a strong position; at or below the second,
#: a thin one. Between them the carrier is unremarkable in the slice and saying
#: so adds nothing.
STRONG_WALLET = 25.0
THIN_WALLET = 10.0

#: Headroom below this is not worth a sentence whatever the percentages say.
MATERIAL_HEADROOM = 1.0

LENS = "positioning"


def _fact(position: SlicePosition, dimension: str, metric: str,
          value: float, unit: str) -> AnswerFact:
    """One positioning figure as a verifiable fact.

    `source_id` names the pack rather than a query so provenance points at the
    thing that computed it, and the id is derived from content so the same figure
    is the same fact however often it is rebuilt.
    """
    dims = ((dimension.lower(), position.slice),)
    identity = (LENS, dims, metric, value, unit)
    return AnswerFact(
        id=stable_id("f_", identity),
        metric=metric,
        value=value,
        unit=unit,
        rendered=format_value(value, unit),
        dimensions=dims,
        source_id=LENS,
        lens=LENS,
        formula=_FORMULAE.get(metric, ""),
    )


_FORMULAE = {
    "share_of_wallet": "carrier premium / Marsh book premium for the slice * 100",
    "share_of_portfolio": "slice premium / carrier total premium * 100",
    "premium": "SUM(Premium) over the slice",
    "marsh_book_premium": "SUM(Premium) over all carriers in the slice",
    "headroom": "Marsh book premium - carrier premium for the slice",
    "rank": "position by premium among carriers in the slice",
    "carriers_in_line": "count of carriers writing the slice",
}


@dataclass(frozen=True)
class PositioningClaims:
    """The claims and the facts they cite, kept together so neither is orphaned."""

    claims: Tuple[AnswerClaim, ...] = ()
    facts: Tuple[AnswerFact, ...] = ()


def _notable(position: SlicePosition) -> bool:
    """Whether this slice's position is worth a sentence of its own.

    Without this every product gets a line and the answer becomes the list of
    numbers it is supposed to replace. A position earns a sentence by being
    concentrated, strong, thin, or top of its market — that is, by being
    something a reader would do something about.
    """
    if position.share_of_portfolio is not None and position.share_of_portfolio >= CONCENTRATED:
        return True
    if position.share_of_wallet is not None and (
        position.share_of_wallet >= STRONG_WALLET or position.share_of_wallet <= THIN_WALLET
    ):
        return True
    return position.rank == 1


def scale_and_penetration(position: SlicePosition, dimension: str) -> Optional[Tuple[AnswerClaim, List[AnswerFact]]]:
    """The core insight sentence: how big the line is, and how much of it is held.

    The two numbers are deliberately in one sentence. Apart they are two facts;
    together they are the argument — a line that is most of the carrier's book
    while holding little of the market is a different business problem from one
    that is small but dominant, and only the pairing shows which.
    """
    if position.share_of_portfolio is None or position.share_of_wallet is None:
        return None
    if position.carrier_premium is None:
        return None

    facts = [
        _fact(position, dimension, "premium", position.carrier_premium, "currency"),
        _fact(position, dimension, "share_of_portfolio", position.share_of_portfolio, "percent"),
        _fact(position, dimension, "share_of_wallet", position.share_of_wallet, "percent"),
    ]
    text = (
        f"{position.slice} is {format_value(position.share_of_portfolio, 'percent')} of the "
        f"carrier's book at {format_value(position.carrier_premium, 'currency')}, and holds "
        f"{format_value(position.share_of_wallet, 'percent')} of Marsh's "
        f"{position.slice} premium"
    )
    if position.marsh_premium is not None:
        facts.append(_fact(position, dimension, "marsh_book_premium", position.marsh_premium, "currency"))
        text += f" of {format_value(position.marsh_premium, 'currency')}"
    standing = _standing(position)
    if standing:
        # Rank and the size of the field are recorded as facts, not just written
        # into the sentence. A stored answer verifies by recompiling its claims
        # from the facts it saved, so a clause built from a figure no fact
        # carries would silently vanish on reload and the answer would stop
        # verifying — which is exactly what happened before these two existed.
        facts.append(_fact(position, dimension, "rank", float(position.rank or 0), "rank"))
        facts.append(_fact(position, dimension, "carriers_in_line", float(position.rank_of or 0), "rank"))
    text += standing + "."

    formula = (
        f"share of portfolio = {position.carrier_premium:g} / carrier total * 100; "
        f"share of wallet = {position.carrier_premium:g} / {position.marsh_premium or 0:g} * 100"
    )
    claim = AnswerClaim(
        id=stable_id("c_", [tuple(sorted(f.id for f in facts)), "position"]),
        text=text,
        fact_ids=tuple(sorted(f.id for f in facts)),
        kind="position",
        formula=formula,
        priority=_priority(position),
    )
    return claim, facts


def _standing(position: SlicePosition) -> str:
    """The rank clause, only when a rank against other carriers exists.

    A rank of one out of one is not a standing — it means the slice has a single
    carrier, and reporting it as "#1" would read as a competitive win.
    """
    if position.rank is None or not position.rank_of or position.rank_of < 2:
        return ""
    return f", ranking {_ordinal(position.rank)} of {position.rank_of} carriers in that line"


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        return f"{value}th"
    return f"{value}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(value % 10, 'th') }"


#: How much each signal counts towards leading the answer. Share of the
#: carrier's own book dominates deliberately: a line that is most of the book
#: drives the result, while a dominant share of a tiny line is a curiosity. With
#: these weighted equally, "100% of a $190k line" outranked "62% of the book",
#: which is the wrong sentence to open with.
_SCALE_WEIGHT = 0.5
_EXTREMITY_WEIGHT = 0.15


def _priority(position: SlicePosition) -> float:
    """Lines that matter to the carrier lead; extreme positions break ties."""
    score = 30.0
    if position.share_of_portfolio is not None:
        score += position.share_of_portfolio * _SCALE_WEIGHT
    if position.share_of_wallet is not None:
        # Distance from an unremarkable middle, in either direction — a very
        # strong and a very thin position are both worth saying.
        middle = (STRONG_WALLET + THIN_WALLET) / 2
        score += abs(position.share_of_wallet - middle) * _EXTREMITY_WEIGHT
    return score


def headroom_claim(pack: PositioningPack) -> Optional[Tuple[AnswerClaim, List[AnswerFact]]]:
    """Where the most Marsh premium sits that this carrier does not hold.

    Phrased as an observation about the book, never as an opportunity: the
    premium is already placed with someone, and calling it winnable asserts
    appetite and capacity this data cannot show.
    """
    position = pack.largest_headroom()
    if position is None or (position.headroom or 0.0) < MATERIAL_HEADROOM:
        return None
    if position.carrier_premium is None or position.marsh_premium is None:
        return None

    facts = [
        _fact(position, pack.dimension, "headroom", position.headroom or 0.0, "currency"),
        _fact(position, pack.dimension, "marsh_book_premium", position.marsh_premium, "currency"),
    ]
    text = (
        f"The largest unheld book is in {position.slice}: "
        f"{format_value(position.headroom or 0.0, 'currency')} of Marsh's "
        f"{format_value(position.marsh_premium, 'currency')} is placed with other carriers."
    )
    claim = AnswerClaim(
        id=stable_id("c_", [tuple(sorted(f.id for f in facts)), "headroom"]),
        text=text,
        fact_ids=tuple(sorted(f.id for f in facts)),
        kind="headroom",
        formula=f"{position.marsh_premium:g} - {position.carrier_premium:g}",
        priority=28.0,
    )
    return claim, facts


def concentration_claim(pack: PositioningPack) -> Optional[Tuple[AnswerClaim, List[AnswerFact]]]:
    """How much of the book sits in its largest line — a risk statement.

    Emitted only when the leading line is genuinely concentrated, because
    "the biggest line is the biggest" is not a finding.
    """
    ranked = [p for p in pack.by_premium() if p.share_of_portfolio is not None]
    if len(ranked) < 2:
        return None
    leader = ranked[0]
    if (leader.share_of_portfolio or 0.0) < CONCENTRATED:
        return None

    facts = [_fact(leader, pack.dimension, "share_of_portfolio", leader.share_of_portfolio or 0.0, "percent")]
    text = (
        f"The book is concentrated: {leader.slice} alone is "
        f"{format_value(leader.share_of_portfolio or 0.0, 'percent')} of premium across "
        f"{len(ranked)} lines, so the carrier's result largely follows that one line."
    )
    claim = AnswerClaim(
        id=stable_id("c_", [tuple(f.id for f in facts), "concentration"]),
        text=text,
        fact_ids=tuple(f.id for f in facts),
        kind="concentration",
        formula=f"largest line share = {leader.share_of_portfolio or 0.0:g}%",
        priority=27.0,
    )
    return claim, facts


def compile_positioning(pack: PositioningPack, *, limit: int = 3) -> PositioningClaims:
    """Every positioning claim this pack supports, strongest first.

    `limit` bounds the per-slice sentences so a twelve-product book does not
    produce twelve near-identical lines; the portfolio-level claims are not
    counted against it because there is at most one of each.
    """
    if not pack:
        return PositioningClaims()

    claims: List[AnswerClaim] = []
    facts: List[AnswerFact] = []

    notable = [p for p in pack.by_premium() if _notable(p)]
    for position in notable:
        built = scale_and_penetration(position, pack.dimension)
        if built is None:
            continue
        claim, cited = built
        claims.append(claim)
        facts.extend(cited)
        if len([c for c in claims if c.kind == "position"]) >= limit:
            break

    for builder in (concentration_claim, headroom_claim):
        built = builder(pack)
        if built is not None:
            claim, cited = built
            claims.append(claim)
            facts.extend(cited)

    unique_facts = {fact.id: fact for fact in facts}
    return PositioningClaims(
        tuple(sorted(claims, key=lambda c: (-c.priority, c.id))),
        tuple(unique_facts.values()),
    )


# --------------------------------------------------------------------------- #
# Rebuilding positions from evidence
# --------------------------------------------------------------------------- #
#
# The pack is how a position is COMPUTED; facts are how it is STORED. A saved
# answer verifies by recompiling its claims from the evidence it recorded, so a
# positioning claim has to be reconstructible from facts alone — otherwise every
# answer carrying one would stop verifying the moment it was reloaded.
#
# These metric names are the contract between the two. `build_positioning` emits
# rows using the column labels; `core.answers.facts` turns those into facts whose
# `metric` is the column name lowercased with underscores, and this reads them
# back.

_METRIC_FIELDS = {
    "carrier_premium": "carrier_premium",
    "premium": "carrier_premium",
    "marsh_premium": "marsh_premium",
    "marsh_book_premium": "marsh_premium",
    "share_of_wallet": "share_of_wallet",
    "share_of_portfolio": "share_of_portfolio",
    "rank": "rank",
    "carriers_in_line": "rank_of",
}


def _slice_of(fact: AnswerFact, dimension: str) -> str:
    wanted = dimension.lower()
    for key, value in fact.dimensions:
        if key.lower() == wanted:
            return str(value)
    return ""


def positions_from_facts(
    facts: Sequence[AnswerFact], dimension: str = "product_line"
) -> PositioningPack:
    """Rebuild a `PositioningPack` from the facts an answer recorded.

    Only facts produced by the positioning lens are read, so an ordinary premium
    breakdown in the same turn cannot be mistaken for a position — it carries no
    share-of-wallet, and a position without one is not a position.
    """
    by_slice: dict = {}
    for fact in facts:
        if fact.lens != LENS:
            continue
        field_name = _METRIC_FIELDS.get(fact.metric.lower())
        name = _slice_of(fact, dimension)
        if not field_name or not name:
            continue
        value = float(fact.value)
        # Rank and field size are whole positions, and `SlicePosition` compares
        # them as ints; a float here would make a rebuilt position unequal to the
        # one it was rebuilt from.
        by_slice.setdefault(name, {})[field_name] = (
            int(value) if field_name in {"rank", "rank_of"} else value
        )

    positions = tuple(
        SlicePosition(slice=name, **values)
        for name, values in sorted(by_slice.items())
        if values
    )
    return PositioningPack(positions, dimension)


def positioning_claims(pack_facts: Sequence[AnswerFact], question: str = "") -> Tuple[AnswerClaim, ...]:
    """Positioning claims for whatever positions the recorded facts describe.

    The entry point `core.answers.insights` calls. Returns nothing when the turn
    gathered no positioning evidence, which is every turn that did not ask for it.
    """
    pack = positions_from_facts(pack_facts)
    return compile_positioning(pack).claims if pack else ()
