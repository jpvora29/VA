"""Where a carrier STANDS in each slice, not just how much it wrote.

A premium figure on its own is a fact with no argument attached. "$900k in
Property" tells a reader nothing they can act on; "$900k in Property, 62% of the
carrier's own book but only 12% of Marsh's Property wallet, ranked 4th" tells
them where the opportunity is. The difference is not wording — it is four more
numbers, and until now nothing gathered them together.

This composes the signed-off primitives into ONE row per slice:

    carrier premium    what this carrier wrote            compute_breakdown
    marsh premium      what the whole book wrote          compute_market_presence
    share of wallet    carrier / market, per slice        compute_share_of_wallet
    share of portfolio this slice's share of the carrier  compute_share_of_portfolio
    rank               where the carrier sits in slice    compute_rank
    movement           year-on-year change and its share  compute_contribution

It owns no arithmetic of its own — every number comes from the primitive that
already defines it, so a definition changes in one place and this follows. What
it owns is the JOIN: aligning six independently-computed fact lists onto the same
slice key, and being explicit about a slice where one of them is missing rather
than rendering a confident zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.analytics.library import (
    compute_breakdown,
    compute_market_presence,
    compute_rank,
    compute_share_of_portfolio,
    compute_share_of_wallet,
)
from core.analytics.movement import compute_contribution
from core.analytics.types import AnalyticsFact, PrimitiveArgs

#: Column labels the table and the claims both read. Named once so a rename
#: cannot leave the prose describing a column the table no longer has.
SLICE = "Slice"
CARRIER_PREMIUM = "Carrier premium"
MARSH_PREMIUM = "Marsh premium"
SHARE_OF_WALLET = "Share of wallet"
SHARE_OF_PORTFOLIO = "Share of portfolio"
RANK = "Rank"
MOVEMENT = "YoY change"
CONTRIBUTION = "Contribution"

#: Order the columns appear in. Carrier premium first because it is what was
#: asked about; the market beside it because that is what makes it mean anything.
COLUMNS: Tuple[str, ...] = (
    SLICE, CARRIER_PREMIUM, MARSH_PREMIUM, SHARE_OF_WALLET,
    SHARE_OF_PORTFOLIO, RANK, MOVEMENT, CONTRIBUTION,
)


@dataclass(frozen=True)
class SlicePosition:
    """One slice's full position. Every figure optional — absent is not zero."""

    slice: str
    carrier_premium: Optional[float] = None
    marsh_premium: Optional[float] = None
    share_of_wallet: Optional[float] = None
    share_of_portfolio: Optional[float] = None
    rank: Optional[int] = None
    rank_of: Optional[int] = None
    movement: Optional[float] = None
    contribution_pp: Optional[float] = None
    prior_premium: Optional[float] = None

    @property
    def has_position(self) -> bool:
        """Whether there is enough here to say anything about standing."""
        return self.share_of_wallet is not None or self.rank is not None

    @property
    def headroom(self) -> Optional[float]:
        """Marsh book this carrier does NOT hold in the slice.

        Named headroom, not opportunity: it is premium someone else already
        writes, which is an observation. Calling it winnable would assert an
        appetite the premium book cannot show (see `core/definitions/terms.yaml`).
        """
        if self.marsh_premium is None or self.carrier_premium is None:
            return None
        return max(0.0, self.marsh_premium - self.carrier_premium)


@dataclass(frozen=True)
class PositioningPack:
    """Every slice's position, plus what could not be computed."""

    positions: Tuple[SlicePosition, ...] = ()
    dimension: str = ""
    missing: Tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.positions)

    def by_premium(self) -> Tuple[SlicePosition, ...]:
        return tuple(sorted(
            self.positions,
            key=lambda p: (p.carrier_premium is None, -(p.carrier_premium or 0.0)),
        ))

    def strongest_position(self) -> Optional[SlicePosition]:
        """Highest share of wallet among slices that have one."""
        scored = [p for p in self.positions if p.share_of_wallet is not None]
        return max(scored, key=lambda p: p.share_of_wallet) if scored else None

    def weakest_position(self) -> Optional[SlicePosition]:
        """Lowest share of wallet in a slice where the market is material.

        Restricted to slices the carrier actually writes: a slice it is absent
        from is whitespace, which is a different finding with its own rules.
        """
        scored = [
            p for p in self.positions
            if p.share_of_wallet is not None and (p.carrier_premium or 0.0) > 0
        ]
        return min(scored, key=lambda p: p.share_of_wallet) if scored else None

    def largest_headroom(self) -> Optional[SlicePosition]:
        scored = [p for p in self.positions if p.headroom]
        return max(scored, key=lambda p: p.headroom or 0.0) if scored else None

    def rows(self) -> List[Dict[str, Any]]:
        """The table as a reader sees it: formatted, with absences left blank."""
        return [_row(position, self.dimension) for position in self.by_premium()]

    def numeric_rows(self) -> List[Dict[str, Any]]:
        """The same table as TYPED numbers, for the fact and claim layers.

        Two renderings of one thing, deliberately. The display rows carry "50.8%"
        because that is what belongs in a cell; the fact layer needs 50.8, because
        a claim that cannot compare its own figures cannot be verified. Deriving
        both from the same positions is what keeps them from disagreeing.

        Keys are the column labels so the fact layer names a metric the reader can
        find in the table, and a column with no value is OMITTED rather than sent
        as null — an absent figure must not become a fact worth 0.0.
        """
        out: List[Dict[str, Any]] = []
        for position in self.by_premium():
            row: Dict[str, Any] = {self.dimension or SLICE: position.slice}
            for column, value in (
                (CARRIER_PREMIUM, position.carrier_premium),
                (MARSH_PREMIUM, position.marsh_premium),
                (SHARE_OF_WALLET, position.share_of_wallet),
                (SHARE_OF_PORTFOLIO, position.share_of_portfolio),
                (MOVEMENT, position.movement),
                (CONTRIBUTION, position.contribution_pp),
            ):
                if value is not None:
                    row[column] = value
            if position.rank is not None:
                row[RANK] = position.rank
            out.append(row)
        return out


def _row(position: SlicePosition, dimension: str) -> Dict[str, Any]:
    rank = (
        f"#{position.rank} of {position.rank_of}"
        if position.rank is not None and position.rank_of
        else (f"#{position.rank}" if position.rank is not None else None)
    )
    return {
        dimension or SLICE: position.slice,
        CARRIER_PREMIUM: _money(position.carrier_premium),
        MARSH_PREMIUM: _money(position.marsh_premium),
        SHARE_OF_WALLET: _percent(position.share_of_wallet),
        SHARE_OF_PORTFOLIO: _percent(position.share_of_portfolio),
        RANK: rank,
        MOVEMENT: _money(position.movement, signed=True),
        CONTRIBUTION: _points(position.contribution_pp),
    }


def _money(value: Optional[float], *, signed: bool = False) -> Optional[str]:
    if value is None:
        return None
    return f"{value:+,.0f}" if signed else f"{value:,.0f}"


def _percent(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{value:.1f}%"


def _points(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{value:+.1f} pts"


# --------------------------------------------------------------------------- #
# Building the pack
# --------------------------------------------------------------------------- #


def _keyed(facts: Sequence[AnalyticsFact], dimension: str) -> Dict[str, AnalyticsFact]:
    """fact list -> {slice value: fact}, keeping the first of any duplicate."""
    out: Dict[str, AnalyticsFact] = {}
    for fact in facts:
        value = fact.dims.get(dimension)
        if value is None:
            continue
        out.setdefault(str(value), fact)
    return out


def _safe(label: str, call, missing: List[str]) -> List[AnalyticsFact]:
    """Run one primitive; record its name and carry on if it cannot run.

    A positioning table that loses its rank column is still worth showing. One
    that raises because the warehouse has no Peers table is not an answer at all,
    and the reader is better served by six columns and a note than by nothing.
    """
    try:
        return list(call())
    except Exception:  # noqa: BLE001 - a missing column must not sink the table
        missing.append(label)
        return []


def build_positioning(
    *,
    flow: str = "gpr",
    dimension: str = "Product_Line",
    filters: Optional[Mapping[str, Any]] = None,
    subject: str = "",
    metric: str = "premium",
    engine: Any = None,
) -> PositioningPack:
    """Assemble one row per slice of `dimension`, under `filters`.

    `subject` is the carrier whose position is being described; share of wallet
    and rank are meaningless without one, so they are skipped rather than guessed
    when it is absent.
    """
    scope = dict(filters or {})
    args = PrimitiveArgs(
        flow=flow, metric=metric, group_by=(dimension,), filters=scope, subject=subject or None
    )
    # Rank is a position AMONG carriers, so it has to see the other carriers.
    # Computed inside the subject's own filter it ranks the carrier against
    # itself and reports "#1 of 1" for every slice — a real number, always
    # wrong, and the kind that looks plausible in a table.
    market_args = PrimitiveArgs(
        flow=flow, metric=metric, group_by=(dimension,),
        filters=_without_carrier(flow, scope), subject=subject or None,
    )
    missing: List[str] = []

    carrier = _keyed(_safe(CARRIER_PREMIUM, lambda: compute_breakdown(args, engine=engine), missing), dimension)
    market = _keyed(_safe(MARSH_PREMIUM, lambda: compute_market_presence(args, engine=engine), missing), dimension)
    appetite = _keyed(_safe(SHARE_OF_PORTFOLIO, lambda: compute_share_of_portfolio(args, engine=engine), missing), dimension)
    wallet = (
        _keyed(_safe(SHARE_OF_WALLET, lambda: compute_share_of_wallet(args, engine=engine), missing), dimension)
        if subject else {}
    )
    ranks = (
        _rank_index(_safe(RANK, lambda: compute_rank(market_args, engine=engine), missing), dimension, subject)
        if subject else {}
    )
    movement = _movement_index(
        _safe(MOVEMENT, lambda: compute_contribution(args, engine=engine), missing), dimension
    )

    slices = sorted(set(carrier) | set(market) | set(appetite))
    positions = tuple(
        SlicePosition(
            slice=name,
            carrier_premium=_value(carrier.get(name)),
            marsh_premium=_value(market.get(name)),
            share_of_wallet=_value(wallet.get(name)),
            share_of_portfolio=_value(appetite.get(name)),
            rank=ranks.get(name, (None, None))[0],
            rank_of=ranks.get(name, (None, None))[1],
            movement=movement.get(name, {}).get("change"),
            contribution_pp=movement.get(name, {}).get("contribution_pp"),
            prior_premium=movement.get(name, {}).get("prior"),
        )
        for name in slices
    )
    return PositioningPack(positions, dimension, tuple(dict.fromkeys(missing)))


def _without_carrier(flow: str, filters: Mapping[str, Any]) -> Dict[str, Any]:
    """`filters` minus the carrier, read from the registry rather than hardcoded."""
    from core.registry import get_flow_registry

    spec = get_flow_registry().get(flow)
    carrier = (getattr(spec, "entity_columns", {}) or {}).get("carrier") if spec else None
    return {k: v for k, v in filters.items() if k != carrier}


def _value(fact: Optional[AnalyticsFact]) -> Optional[float]:
    return None if fact is None else float(fact.value)


def _rank_index(
    facts: Sequence[AnalyticsFact], dimension: str, subject: str
) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """{slice: (rank, field size)} for the subject carrier only.

    `compute_rank` ranks every carrier in every slice; only the subject's row is
    this carrier's position, and taking the first row per slice would report
    whoever happens to lead it.
    """
    out: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    wanted = (subject or "").strip().lower()
    for fact in facts:
        name = fact.dims.get(dimension)
        entity = str(fact.dims.get("entity", "")).strip().lower()
        if name is None or entity != wanted:
            continue
        support = fact.support[0] if fact.support else {}
        of_n = support.get("of_n")
        out[str(name)] = (int(fact.value), int(of_n) if of_n is not None else None)
    return out


def _movement_index(
    facts: Sequence[AnalyticsFact], dimension: str
) -> Dict[str, Dict[str, Optional[float]]]:
    """{slice: {change, contribution_pp, prior}} from the contribution facts."""
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for fact in facts:
        if fact.name != "contribution":
            continue
        name = fact.dims.get(dimension)
        if name is None:
            continue
        support = fact.support[0] if fact.support else {}
        prior_year = str(fact.dims.get("prior_year", ""))
        out[str(name)] = {
            "change": float(fact.value),
            "contribution_pp": fact.dims.get("contribution_pp"),
            "prior": support.get(prior_year),
        }
    return out
