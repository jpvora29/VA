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


#: Claim kinds a penetration question is actually about. Asked "where can we
#: grow", a reader wants the unheld book and the thin positions first; the
#: largest line's scale is the answer to a different question.
PENETRATION_FIRST = ("headroom", "position")

PENETRATION = "penetration"


def compile_positioning(pack: PositioningPack, *, limit: int = 3,
                        focus: str = "") -> PositioningClaims:
    """Every positioning claim this pack supports, strongest first.

    `limit` bounds the per-slice sentences so a twelve-product book does not
    produce twelve near-identical lines; the portfolio-level claims are not
    counted against it because there is at most one of each.
    """
    if not pack:
        return PositioningClaims()

    claims: List[AnswerClaim] = []
    facts: List[AnswerFact] = []

    # A penetration question is about where the carrier is THIN, so the slices
    # worth a sentence are ranked by unheld book rather than by size. Asked
    # "where can we grow", leading with the biggest line answers "where are we
    # already big" — a true sentence about the wrong thing.
    if focus == PENETRATION:
        notable = [p for p in pack.positions if p.headroom]
        notable.sort(key=lambda p: p.headroom or 0.0, reverse=True)
    else:
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

    # Cross-metric readings first: they say something no single column does, so
    # they earn their place ahead of another per-slice description.
    for position in pack.by_premium():
        built = ground_claim(position, pack.dimension)
        if built is not None:
            claim, cited = built
            claims.append(claim)
            facts.extend(cited)
            break

    for builder in (mix_shift_claim, standing_claim, concentration_claim, headroom_claim):
        built = builder(pack)
        if built is not None:
            claim, cited = built
            claims.append(claim)
            facts.extend(cited)

    unique_facts = {fact.id: fact for fact in facts}
    ordered = sorted(claims, key=lambda c: (-c.priority, c.id))
    if focus == PENETRATION:
        # Re-rank rather than re-score: the claims themselves are unchanged, it
        # is only which of them answers THIS question that differs.
        rank = {kind: index for index, kind in enumerate(PENETRATION_FIRST)}
        ordered = sorted(ordered, key=lambda c: rank.get(c.kind, len(rank)))
    return PositioningClaims(tuple(ordered), tuple(unique_facts.values()))


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
    # The prior period. Without these a reloaded answer keeps its levels and
    # loses every sentence about direction, which is most of the analysis.
    "prior_premium": "prior_premium",
    "prior_share_of_wallet": "prior_share_of_wallet",
    "prior_share_of_portfolio": "prior_share_of_portfolio",
    "prior_rank": "prior_rank",
}

#: Fields `SlicePosition` holds as whole numbers. A float here would make a
#: rebuilt position compare unequal to the one it was rebuilt from.
_WHOLE_FIELDS = frozenset({"rank", "rank_of", "prior_rank"})


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
            int(value) if field_name in _WHOLE_FIELDS else value
        )

    positions = tuple(
        SlicePosition(slice=name, **values)
        for name, values in sorted(by_slice.items())
        if values
    )
    return PositioningPack(positions, dimension)


def focus_for(question: str) -> str:
    """Which reading of a position THIS question is asking for.

    Deterministic and deliberately narrow: only a question that actually asks
    about growing or penetrating re-ranks the claims. Everything else keeps the
    default ordering, so a performance answer is unaffected.
    """
    from core.analysis.operation import PENETRATION as PENETRATION_INTENT, detect_operation

    return PENETRATION if detect_operation(question) == PENETRATION_INTENT else ""


def positioning_claims(pack_facts: Sequence[AnswerFact], question: str = "") -> Tuple[AnswerClaim, ...]:
    """Positioning claims for whatever positions the recorded facts describe.

    The entry point `core.answers.insights` calls. Returns nothing when the turn
    gathered no positioning evidence, which is every turn that did not ask for it.
    """
    pack = positions_from_facts(pack_facts)
    return compile_positioning(pack, focus=focus_for(question)).claims if pack else ()


# --------------------------------------------------------------------------- #
# Cross-metric readings — the insight a single column cannot give
# --------------------------------------------------------------------------- #
#
# Everything above describes one measure at a time. These read TWO against each
# other, which is where the analysis actually lives: premium and share together
# say whether a decline was the carrier's or the market's; mix and premium
# together say whether the book is changing shape; rank against premium says
# whether a fall cost the carrier anything competitively.
#
# Each is emitted only when the two measures genuinely disagree or genuinely
# reinforce — a line that fell while losing share in the ordinary way gets the
# ordinary movement sentence instead.

#: Share movement below this is noise on a book of any size.
MATERIAL_POINTS = 1.0


def ground_claim(position: SlicePosition, dimension: str) -> Optional[Tuple[AnswerClaim, List[AnswerFact]]]:
    """Whether a movement was the carrier's own or the whole market's.

    The reading a premium column cannot give. Premium down and share UP means the
    market fell further and the carrier gained ground; premium up and share DOWN
    means it grew more slowly than the book around it. Both are the opposite of
    what the headline number alone suggests, and both are what a reader needs.
    """
    change, wallet = position.premium_change_percent, position.wallet_change
    if change is None or wallet is None or abs(wallet) < MATERIAL_POINTS:
        return None
    if position.share_of_wallet is None or position.prior_share_of_wallet is None:
        return None

    # The premium pair rides along because the sentence states a percentage
    # change derived from it. A claim that quotes a figure no recorded fact can
    # reproduce silently loses that clause when the answer is reloaded and
    # recompiled — the failure the reconstruction test exists to catch.
    facts = [
        _fact(position, dimension, "share_of_wallet", position.share_of_wallet, "percent"),
        _fact(position, dimension, "prior_share_of_wallet", position.prior_share_of_wallet, "percent"),
        _fact(position, dimension, "premium", position.carrier_premium or 0.0, "currency"),
        _fact(position, dimension, "prior_premium", position.prior_premium or 0.0, "currency"),
    ]
    gained, fell = wallet > 0, change < 0
    if fell and gained:
        text = (
            f"{position.slice} fell {format_value(abs(change), 'percent')} but gained "
            f"{format_value(abs(wallet), 'percentage_points')} of wallet share, so the "
            f"wider Marsh book fell further — this is lost volume, not lost position."
        )
    elif not fell and not gained:
        text = (
            f"{position.slice} grew {format_value(change, 'percent')} yet gave up "
            f"{format_value(abs(wallet), 'percentage_points')} of wallet share, so it grew "
            f"more slowly than the Marsh book around it."
        )
    elif fell and not gained:
        text = (
            f"{position.slice} fell {format_value(abs(change), 'percent')} and gave up "
            f"{format_value(abs(wallet), 'percentage_points')} of wallet share, so the "
            f"decline ran ahead of the market's rather than following it."
        )
    else:
        text = (
            f"{position.slice} grew {format_value(change, 'percent')} and took "
            f"{format_value(abs(wallet), 'percentage_points')} more of the wallet, "
            f"outpacing the Marsh book in that line."
        )
    claim = AnswerClaim(
        id=stable_id("c_", [tuple(sorted(f.id for f in facts)), "ground"]),
        text=text,
        fact_ids=tuple(sorted(f.id for f in facts)),
        kind="ground",
        formula=(
            f"share of wallet {position.prior_share_of_wallet:g}% -> "
            f"{position.share_of_wallet:g}%; premium change {change:g}%"
        ),
        priority=46.0,
    )
    return claim, facts


def mix_shift_claim(pack: PositioningPack) -> Optional[Tuple[AnswerClaim, List[AnswerFact]]]:
    """The line whose share of the carrier's own book moved most.

    A book changing shape is a strategic fact no single premium figure shows:
    every line can fall while one of them still becomes a bigger part of what the
    carrier writes.
    """
    scored = [p for p in pack.positions if p.portfolio_change is not None]
    if not scored:
        return None
    mover = max(scored, key=lambda p: abs(p.portfolio_change or 0.0))
    change = mover.portfolio_change or 0.0
    if abs(change) < MATERIAL_POINTS:
        return None
    if mover.share_of_portfolio is None or mover.prior_share_of_portfolio is None:
        return None

    facts = [
        _fact(mover, pack.dimension, "share_of_portfolio", mover.share_of_portfolio, "percent"),
        _fact(mover, pack.dimension, "prior_share_of_portfolio", mover.prior_share_of_portfolio, "percent"),
    ]
    direction = "a larger" if change > 0 else "a smaller"
    text = (
        f"The book is changing shape: {mover.slice} moved from "
        f"{format_value(mover.prior_share_of_portfolio, 'percent')} to "
        f"{format_value(mover.share_of_portfolio, 'percent')} of premium, {direction} "
        f"part of what the carrier writes."
    )
    claim = AnswerClaim(
        id=stable_id("c_", [tuple(sorted(f.id for f in facts)), "mix_shift"]),
        text=text,
        fact_ids=tuple(sorted(f.id for f in facts)),
        kind="mix_shift",
        formula=(
            f"share of portfolio {mover.prior_share_of_portfolio:g}% -> "
            f"{mover.share_of_portfolio:g}%"
        ),
        priority=42.0,
    )
    return claim, facts


def standing_claim(pack: PositioningPack) -> Optional[Tuple[AnswerClaim, List[AnswerFact]]]:
    """A rank read against the premium that moved under it.

    "Down 25% but still first in the line" and "up but slipped a place" are both
    readings that a premium column and a rank column only give together.
    """
    for position in pack.by_premium():
        change, moved = position.premium_change_percent, position.rank_change
        if change is None or moved is None or position.rank is None:
            continue
        if change >= 0 and moved >= 0:
            continue  # grew and held or improved: the unremarkable case
        facts = [
            _fact(position, pack.dimension, "rank", float(position.rank), "rank"),
            _fact(position, pack.dimension, "prior_rank", float(position.prior_rank or 0), "rank"),
            _fact(position, pack.dimension, "premium", position.carrier_premium or 0.0, "currency"),
            _fact(position, pack.dimension, "prior_premium", position.prior_premium or 0.0, "currency"),
        ]
        if moved == 0:
            text = (
                f"Despite the fall, {position.slice} held {_ordinal(position.rank)} place "
                f"among carriers in that line — the position survived the volume."
            )
        elif moved < 0:
            text = (
                f"{position.slice} slipped from {_ordinal(position.prior_rank or 0)} to "
                f"{_ordinal(position.rank)} among carriers in that line."
            )
        else:
            text = (
                f"{position.slice} rose from {_ordinal(position.prior_rank or 0)} to "
                f"{_ordinal(position.rank)} among carriers in that line even as premium fell."
            )
        claim = AnswerClaim(
            id=stable_id("c_", [tuple(sorted(f.id for f in facts)), "standing"]),
            text=text,
            fact_ids=tuple(sorted(f.id for f in facts)),
            kind="standing",
            formula=f"rank {position.prior_rank} -> {position.rank}",
            priority=38.0,
        )
        return claim, facts
    return None
