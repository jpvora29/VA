"""Postures on the page — one book's stance, and the portfolio's stance across products.

:mod:`studio.posture` decides a stance from figures; this turns a decision into the line a
slide carries, and is the only place the deck's fact dictionaries are mapped onto
:class:`~studio.posture.PostureInput`.

Two surfaces, because a QBR answers the question at two altitudes:

  * a product page states ITS book's posture, from the facts that page already loaded;
  * the overall page states the PORTFOLIO's, grouping every product by the stance its own
    figures earn — which is what an executive summary is for, instead of restating six
    products' growth rates one after another.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from logger import get_logger
from studio.posture import Posture, PostureInput, call_phrase, posture_for
from studio.template_fill.render import _money

logger = get_logger(__name__)

if TYPE_CHECKING:
    from studio.narrative import SlideNarrative

_PRODUCT_COL = "Product_Line"

# The order a portfolio line reads in: what must be held, what can be pressed, what is
# broken, what needs checking, then the rest. It is the order of a management agenda.
_AGENDA: Tuple[Posture, ...] = (
    Posture.DEFEND, Posture.SCALE, Posture.FIX, Posture.VALIDATE, Posture.SELECTIVE,
)


def _input_from_facts(facts: Dict[str, Any], name: str) -> PostureInput:
    """One book's :class:`PostureInput` from the fact set a feedback panel already has."""
    carrier = facts.get("carrier") or {}
    marsh = facts.get("marsh") or {}
    rank = facts.get("rank") or {}
    sow = facts.get("sow") or {}
    peer = facts.get("peer") or {}
    return PostureInput(
        name=name,
        premium=carrier.get("current"),
        pool=marsh.get("current"),
        growth_pct=carrier.get("pct"),
        pool_growth_pct=marsh.get("pct"),
        rank=int(rank["current"]) if rank.get("current") is not None else None,
        rank_change=int(rank["delta"]) if rank.get("delta") is not None else None,
        share=sow.get("current"),
        share_change=sow.get("delta"),
        peer_share=peer.get("sow"),
    )


def book_posture_point(facts: Dict[str, Any], name: str = "") -> Optional[str]:
    """The stance line for the book a page is about, or ``None`` when unsupported.

    "The call here is to scale this book, because share of wallet rose 1.2 percentage
    points" named nothing a team could act on: every carrier's book is somewhere, and an
    instruction that does not say where is advice true of anyone. Where the scope has been
    decomposed, the call is anchored to the segment carrying the most premium behind it.
    """
    label = name or str(facts.get("subject") or "").strip() or "the book"
    call = posture_for(_input_from_facts(facts, label))
    if call is None:
        return None
    # The reason and the place are both load-bearing, and an earlier draft of this traded
    # the reason away for the place. A stance with no "because" is an assertion; one with
    # no "where" is advice true of any carrier. The line carries both.
    stance = f"The call here is to {call_phrase(call.posture)}, because {call.because}."
    where = _stance_anchor(facts)
    return f"{stance} {where}" if where else stance


def _stance_anchor(facts: Dict[str, Any]) -> Optional[str]:
    """The named segment with the most premium at stake, as a clause for the stance line."""
    from studio.segments import OPPORTUNITY_KINDS
    from studio.template_fill.render import _money

    rows = [r for found in (facts.get("segments") or {}).values()
            for r in found.of(*OPPORTUNITY_KINDS)]
    top = max(rows, key=lambda r: r.stake) if rows else None
    if top is not None and top.stake:
        return (f"{top.name} is where the most premium sits behind it, "
                f"{_money(top.stake)} of it.")
    # A scope shaped like its parent has no segment of its own to name, but it still has a
    # biggest mover -- and an instruction that names nowhere is the advice this deck was
    # rewritten to stop giving.
    movers = [m for m in (facts.get("movers") or [])
              if isinstance(m.get("delta"), (int, float)) and m["delta"] > 0]
    if not movers:
        return None
    lead = max(movers, key=lambda m: m["delta"])
    return (f"{lead['name']} is what moved it, {_money(lead['delta'])} of the year's "
            f"growth.")


# ── the portfolio line ───────────────────────────────────────────────────────


def _and(names: List[str]) -> str:
    if len(names) < 2:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _product_inputs(result) -> List[PostureInput]:
    """One :class:`PostureInput` per product in scope — one breakdown query, plus the pool
    movement the page already loads."""
    from studio.compute import product_breakdown_rows
    from studio.template_fill import feedback
    from studio.template_fill.bindings import reporting_filters

    filters = reporting_filters(result)
    rows = product_breakdown_rows(result.flow, filters, result.engine, result.subject, top=10)
    if len(rows) < 2:
        return []                       # a single-product scope has no portfolio to call
    pool = {str(p.get("name")): p for p in (feedback.facts_for(result).get("pool") or [])}
    out: List[PostureInput] = []
    for row in rows:
        name = str(row.get("name") or "")
        share = row.get("sow")
        out.append(PostureInput(
            name=name,
            premium=row.get("gwp"),
            pool=(row["gwp"] / (share / 100.0)) if share else None,
            growth_pct=row.get("var"),
            pool_growth_pct=(pool.get(name) or {}).get("pct"),
            rank=row.get("rank"),
            rank_change=row.get("rank_change"),
            share=share,
            behind_peer=row.get("runway"),
        ))
    return out


# A management line that names six products is a list, not a call. Two is what a room can
# hold, and it forces the ranking to mean something.
_MAX_PORTFOLIO_CALLS = 2


def portfolio_posture_point(result) -> Optional[str]:
    """Every product grouped by the stance its figures earn, as one management line.

    ``None`` for a scope with fewer than two products (a product sub-deck has no portfolio
    to summarise) or when no product's figures support a call. Never raises: a stance is
    worth a line, never a broken deck.
    """
    try:
        calls: Dict[Posture, List[Tuple[str, Optional[float]]]] = defaultdict(list)
        for x in _product_inputs(result):
            call = posture_for(x)
            if call is not None:
                calls[call.posture].append((x.name, x.premium))
        if not calls:
            return None
        # "Across the book the call is to defend Cyber, scale Financial Lines, fix Casualty
        # and selectively pursue Property, Marine and Energy" named six products, carried
        # no figure, and would have been true of any carrier with six lines. An instruction
        # earns its place by naming what is at stake, so this takes the TWO stances the
        # most premium sits behind and says how much.
        ranked = sorted(((posture, name, premium) for posture, rows in calls.items()
                         for name, premium in rows),
                        key=lambda x: (_AGENDA.index(x[0]), -(x[2] or 0.0)))
        picked = [x for x in ranked[:_MAX_PORTFOLIO_CALLS] if x[2]]
        if not picked:
            return None
        grouped: Dict[Posture, List[str]] = defaultdict(list)
        for posture, name, premium in picked:
            grouped[posture].append(f"{name} ({_money(premium)})")
        parts = [f"{posture.value.lower()} {_and(names)}"
                 for posture, names in grouped.items()]
        return "The book's first calls are to " + _and(parts) + "."
    except Exception as exc:  # noqa: BLE001 — the stance never breaks the deck
        logger.warning("stance: no portfolio posture (%s)", exc)
        return None


# ── the shared narrative contract ────────────────────────────────────────────


# Section topic → the job that page does in the deck. Naming the role is what makes two
# pages' claims comparable: the ledger stops them repeating words, the role stops them
# repeating PURPOSE.
_SLIDE_ROLE: Dict[str, str] = {
    "thesis": "portfolio thesis",
    "reflections": "performance assessment",
    "performance": "performance assessment",
    "priorities": "management agenda",
    "key_messages": "decision brief",
    "working": "trajectory",
    "challenges": "performance concern",
    "growth": "opportunity qualification",
}


def narrative_for(facts: Dict[str, Any], topic: str, *, name: str = "",
                  said: Optional[List[str]] = None,
                  fact_ids: Tuple[str, ...] = ()) -> Optional["SlideNarrative"]:
    """A :class:`~studio.narrative.SlideNarrative` for one page of the template-fill deck.

    Assembles the pieces this package already computes — the composed claim, the derived
    posture, and the ladder's own ceiling on how far a recommendation may go — into the one
    structure every engine shares. Returns ``None`` when the facts carry no claim at all;
    a page with nothing to say has no narrative, rather than an empty one.

    ``said`` is the page's already-composed lines. Pass them whenever the caller has them:
    a prose COLUMN's topic ("performance", "reflections") is not a composer kind, so the
    fallback below would find nothing for it and the page would lose its narrative.
    """
    from studio.narrative import Confidence, SlideNarrative
    from studio.opportunity import level_from_premium_only, qualifier_for
    from studio.template_fill import feedback

    said = list(said) if said else feedback.points(topic, facts)
    if not said:
        return None
    call = posture_for(_input_from_facts(facts, name or str(facts.get("subject") or "")))
    # An opportunity page rests on premium evidence alone, which reaches an observation and
    # no further — so it declares itself unvalidated and names what is missing.
    opportunity = topic == "growth"
    return SlideNarrative(
        slide_role=_SLIDE_ROLE.get(topic, topic),
        primary_claim=said[0],
        evidence_fact_ids=tuple(fact_ids),
        interpretation=said[1] if len(said) > 1 else "",
        management_implication=said[2] if len(said) > 2 else "",
        recommended_action=(f"{call.posture.value} {name}." if call and name
                            else (f"{call.posture.value} this book." if call else "")),
        posture=call.posture if call else None,
        confidence=Confidence.UNVALIDATED if opportunity else Confidence.EVIDENCED,
        open_question=(qualifier_for(level_from_premium_only()).capitalize() + "."
                       if opportunity else ""),
    )


# ── enriching the pool: more DISTINCT things to say, not more repetition ─────
# The claim ledger keeps a claim off a second page, so a deck with a small pool of claims
# ends up with thin later pages. The answer is not to loosen the ledger — it is to give the
# pages more genuinely different things to say. Everything below is derived from the ONE
# breakdown query the postures already make, and every line is a claim no other column
# makes: a per-product stance, the shape of the portfolio, where it is deep and thin.


# Posture → how a per-product recommendation reads as a sentence. No "Name: value" pairs —
# the deck's prose rules refuse them, and they are labels rather than advice.
_PRODUCT_PHRASE = {
    Posture.DEFEND: "{name} is the position to defend, since {because}",
    Posture.SCALE: "{name} is where capacity should go, since {because}",
    Posture.FIX: "{name} needs fixing, since {because}",
    Posture.VALIDATE: "{name} needs validating before capacity follows, since {because}",
    Posture.SELECTIVE: "{name} is one to pursue selectively, since {because}",
}


@dataclass(frozen=True)
class PortfolioExtras:
    """Extra fact-grounded lines for the overall pages, bucketed by the question they answer.

    Bucketed rather than pooled, and that is the point. A single shared list is drained by
    whichever column is filled first, leaving every later column back where it started —
    thin. Each bucket holds claims only ITS column would make, so four columns can each be
    deepened without taking another's material or repeating it.
    """

    priorities: Tuple[str, ...] = ()        # what to do, product by product
    standing: Tuple[str, ...] = ()          # where the book stands across its lines
    movement: Tuple[str, ...] = ()          # which lines beat their own pool
    positioning: Tuple[str, ...] = ()       # rank movement across the book
    penetration: Tuple[str, ...] = ()       # where the wallet is deep and thin

    def for_topic(self, topic: str) -> Tuple[str, ...]:
        return _TOPIC_EXTRAS.get(topic, lambda x: ())(self)


# Column topic to the bucket it draws on. The quadrant kinds map by the question they ask,
# so a country block's panels are deepened the same way the summary pages are.
_TOPIC_EXTRAS: Dict[str, Any] = {
    "priorities": lambda x: x.priorities,
    "thesis": lambda x: x.standing,
    "performance": lambda x: x.movement,
    "reflections": lambda x: x.positioning,
    "key_messages": lambda x: x.penetration,
    "working": lambda x: x.movement,
    "challenges": lambda x: x.positioning,
    "growth": lambda x: x.penetration,
}


def _product_posture_lines(inputs: List[PostureInput], limit: int = 4) -> List[str]:
    """One line per product, in management-agenda order — defend, scale, fix, then the rest.

    The portfolio line compresses every product into one sentence, which is right for an
    executive summary and too little for a priorities column. These are its detail: each
    names a product, its stance, and the figure the stance rests on.
    """
    calls = [(x, posture_for(x)) for x in inputs]
    ranked = sorted(
        ((x, c) for x, c in calls if c is not None),
        key=lambda pair: (_AGENDA.index(pair[1].posture), -(pair[0].premium or 0.0)),
    )
    return [
        _PRODUCT_PHRASE[call.posture].format(name=x.name, because=call.because) + "."
        for x, call in ranked[:limit]
    ]


def _standing_lines(inputs: List[PostureInput]) -> List[str]:
    """Where the book stands across its lines — claims needing every product at once."""
    lines: List[str] = []
    ranked = [x for x in inputs if x.rank is not None]
    if len(ranked) >= 3:
        inside = [x for x in ranked if x.rank <= 5]
        if inside and len(inside) < len(ranked):
            lines.append(
                f"The carrier sits inside the top five in {len(inside)} of its "
                f"{len(ranked)} lines and outside it in {len(ranked) - len(inside)}.")
    sized = sorted((x for x in inputs if x.premium), key=lambda x: -(x.premium or 0.0))
    total = sum(x.premium or 0.0 for x in sized)
    if len(sized) >= 3 and total:
        top = sized[:2]
        share = sum(x.premium or 0.0 for x in top) / total * 100.0
        lines.append(
            f"{_and([x.name for x in top])} carry {_money(sum(x.premium for x in top))} "
            f"between them, {share:.0f}% of everything written.")
    return lines


def _movement_lines(inputs: List[PostureInput]) -> List[str]:
    """Which lines beat their own pool and which trailed it — growth with a benchmark."""
    comparable = [x for x in inputs
                  if x.growth_pct is not None and x.pool_growth_pct is not None]
    if len(comparable) < 2:
        return []
    ahead = sorted((x for x in comparable if x.growth_pct > x.pool_growth_pct),
                   key=lambda x: -(x.growth_pct - x.pool_growth_pct))[:2]
    behind = sorted((x for x in comparable if x.growth_pct < x.pool_growth_pct),
                    key=lambda x: (x.growth_pct - x.pool_growth_pct))[:2]
    lines: List[str] = []
    if ahead:
        lines.append(_and([f"{x.name} grew {x.growth_pct:.1f}% against a pool at "
                           f"{x.pool_growth_pct:.1f}%" for x in ahead])
                     + ", so the share there was won rather than carried.")
    if behind:
        lines.append(_and([f"{x.name} grew {x.growth_pct:.1f}% against a pool at "
                           f"{x.pool_growth_pct:.1f}%" for x in behind])
                     + ", so ground was given there.")
    return lines


def _positioning_lines(inputs: List[PostureInput]) -> List[str]:
    """How the book's RANK moved across its lines — position, not premium."""
    moved = [x for x in inputs if x.rank_change and x.rank is not None]
    if not moved:
        return []
    up = [x for x in moved if x.rank_change > 0]
    down = [x for x in moved if x.rank_change < 0]
    lines: List[str] = []
    if up:
        best = max(up, key=lambda x: x.rank_change)
        lines.append(
            f"Rank improved in {len(up)} of {len(inputs)} lines, furthest in {best.name}, "
            f"up {best.rank_change} places to #{int(best.rank)}.")
    if down:
        worst = min(down, key=lambda x: x.rank_change)
        lines.append(
            f"Rank slipped in {len(down)} of {len(inputs)} lines, furthest in {worst.name}, "
            f"down {abs(worst.rank_change)} places to #{int(worst.rank)}.")
    return lines


def _penetration_lines(inputs: List[PostureInput]) -> List[str]:
    """Where the wallet is deep and where it is thin — and what the thin end is worth."""
    shares = [x for x in inputs if x.share is not None]
    if len(shares) < 2:
        return []
    deep = max(shares, key=lambda x: x.share)
    thin = min(shares, key=lambda x: x.share)
    if deep.name == thin.name:
        return []
    lines = [f"Penetration is deepest in {deep.name} at {deep.share:.1f}% of the wallet "
             f"and thinnest in {thin.name} at {thin.share:.1f}%."]
    if thin.pool and deep.share > thin.share:
        worth = thin.pool * (deep.share - thin.share) / 100.0
        lines.append(
            f"Writing {thin.name} at the same {deep.share:.1f}% would be worth about "
            f"{_money(worth)} of additional GWP at today's pool.")
    return lines


def portfolio_extras(result) -> PortfolioExtras:
    """The extra lines for this run's overall pages — one breakdown query, reused.

    Empty for a single-product scope (a product page has no portfolio to describe) and on
    any failure: extra depth is worth a query, never a broken deck.
    """
    try:
        inputs = _product_inputs(result)
        if not inputs:
            return PortfolioExtras()
        return PortfolioExtras(
            priorities=tuple(_product_posture_lines(inputs)),
            standing=tuple(_standing_lines(inputs)),
            movement=tuple(_movement_lines(inputs)),
            positioning=tuple(_positioning_lines(inputs)),
            penetration=tuple(_penetration_lines(inputs)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("stance: no portfolio extras (%s)", exc)
        return PortfolioExtras()
