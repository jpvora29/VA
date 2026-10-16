"""Premium and portfolio metrics for one slice — pure functions over the premium cube.

Formulas follow design Section 5 exactly; the special cases (new activity, not
applicable, unavailable, nonpositive base) are explicit statuses rather than ``None``s a
reader has to interpret. Shares are recomputed from summed premium at every rollup, never
averaged (design Section 6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

import pandas as pd

from studio.exec_summary.peers import PeerSet

GROWTH_VALID = "valid"
GROWTH_NEW = "new_activity"
GROWTH_NA = "not_applicable"
GROWTH_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Scope:
    """A slice of the book. ``country=None`` means every selected country, summed."""

    country: Optional[str] = None
    product: Optional[str] = None
    industry: Optional[str] = None
    segment: Optional[str] = None

    @property
    def scope_id(self) -> str:
        parts = [self.country or "ALL", self.product or "*", self.industry or "*",
                 self.segment or "*"]
        return "/".join(p.replace("/", "-") for p in parts)

    @property
    def label(self) -> str:
        names = [n for n in (self.industry, self.segment, self.product) if n]
        where = self.country or "selected countries"
        return f"{' / '.join(names)} in {where}" if names else where


@dataclass(frozen=True)
class Growth:
    pct: Optional[float]
    status: str

    @property
    def valid(self) -> bool:
        return self.status == GROWTH_VALID and self.pct is not None


@dataclass(frozen=True)
class PeerReference:
    """The mean of the country's peer set in this slice (user decision: mean, not median)."""

    mean_cur: Optional[float] = None
    mean_prior: Optional[float] = None
    growth: Growth = Growth(None, GROWTH_UNAVAILABLE)
    sow_cur: Optional[float] = None
    sow_prior: Optional[float] = None
    counts: Dict[str, int] = field(default_factory=dict)   # active peers per country

    @property
    def available(self) -> bool:
        return self.mean_cur is not None

    @property
    def count(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class SliceMetrics:
    scope: Scope
    carrier_cur: float
    carrier_prior: float
    marsh_cur: float
    marsh_prior: float
    carrier_growth: Growth
    marsh_growth: Growth
    sow_cur: Optional[float]
    sow_prior: Optional[float]
    rank_cur: Optional[int]
    rank_prior: Optional[int]
    rank_of_n: Optional[int]
    peer: PeerReference
    mix_pct: Optional[float] = None
    mix_parent: str = ""

    @property
    def sow_change_pp(self) -> Optional[float]:
        if self.sow_cur is None or self.sow_prior is None:
            return None
        return self.sow_cur - self.sow_prior

    @property
    def rank_movement(self) -> Optional[int]:
        """Prior rank − current rank: positive is an improvement (design Section 5)."""
        if self.rank_cur is None or self.rank_prior is None:
            return None
        return self.rank_prior - self.rank_cur

    @property
    def growth_gap_marsh_pp(self) -> Optional[float]:
        return gap(self.carrier_growth, self.marsh_growth)

    @property
    def growth_gap_peer_pp(self) -> Optional[float]:
        return gap(self.carrier_growth, self.peer.growth)


# ── formulas ─────────────────────────────────────────────────────────────────


def growth(current: Optional[float], prior: Optional[float]) -> Growth:
    """100 × (current / prior − 1), with the design's special cases named."""
    if current is None or prior is None:
        return Growth(None, GROWTH_UNAVAILABLE)
    if prior == 0 and current > 0:
        return Growth(None, GROWTH_NEW)
    if prior == 0 and current == 0:
        return Growth(None, GROWTH_NA)
    if prior <= 0:
        return Growth(None, GROWTH_UNAVAILABLE)          # nonpositive base: suppressed
    return Growth(100.0 * (current / prior - 1.0), GROWTH_VALID)


def share(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """100 × numerator / denominator; suppressed on a nonpositive denominator."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return 100.0 * numerator / denominator


def gap(a: Growth, b: Growth) -> Optional[float]:
    """Growth gap in percentage points — only when both growths are valid."""
    if not (a.valid and b.valid):
        return None
    return a.pct - b.pct


# ── cutting the cube ─────────────────────────────────────────────────────────


def cut(cube: pd.DataFrame, scope: Scope) -> pd.DataFrame:
    """The rows of one slice (every carrier — the whole Marsh book of that slice)."""
    mask = pd.Series(True, index=cube.index)
    for column, value in (("country", scope.country), ("product", scope.product),
                          ("industry", scope.industry), ("segment", scope.segment)):
        if value is not None:
            mask &= cube[column] == value
    return cube[mask]


def by_carrier(frame: pd.DataFrame, year: int) -> pd.Series:
    """Premium per carrier in one period (carriers with any row)."""
    rows = frame[frame["year"] == year]
    return rows.groupby("carrier")["premium"].sum()


def carrier_premium(per_carrier: pd.Series, carrier: str) -> float:
    lowered = {str(k).lower(): float(v) for k, v in per_carrier.items()}
    return lowered.get(carrier.lower(), 0.0)


def dense_rank(per_carrier: pd.Series, carrier: str) -> Tuple[Optional[int], Optional[int]]:
    """(rank, of_n) by premium descending among carriers with positive premium.

    Dense rank is the design's proposed tie rule. ``None`` when the carrier has no
    positive premium in the slice — a carrier that does not write here has no rank.
    """
    positive = per_carrier[per_carrier > 0]
    own = carrier_premium(positive, carrier)
    if own <= 0:
        return None, int(len(positive)) or None
    distinct = sorted({round(float(v), 6) for v in positive.values}, reverse=True)
    return distinct.index(round(own, 6)) + 1, int(len(positive))


def _country_peer_means(frame: pd.DataFrame, members: Tuple[str, ...], current: int,
                        prior: int) -> Tuple[Optional[float], Optional[float], int]:
    """Mean premium of the peers ACTIVE in the current period, and the same peers' prior.

    Same membership in both periods (design Section 6, historical comparison), so the peer
    growth is a like-for-like pooled growth of the current active peers.
    """
    wanted = {m.lower() for m in members}
    now = by_carrier(frame, current)
    before = by_carrier(frame, prior)
    active = [c for c, v in now.items() if str(c).lower() in wanted and v > 0]
    if not active:
        return None, None, 0
    mean_now = float(sum(now[c] for c in active)) / len(active)
    mean_before = float(sum(before.get(c, 0.0) for c in active)) / len(active)
    return mean_now, mean_before, len(active)


def peer_reference(frame: pd.DataFrame, scope: Scope, peer_sets: Mapping[str, PeerSet],
                   current: int, prior: int, marsh_cur: float,
                   marsh_prior: float) -> PeerReference:
    """Country references first; a multi-country reference is their SUM (never a union).

    For one country this is the mean premium of its peer set. Across countries it is the
    sum of each country's own peer mean — a typical peer's footprint over the same markets
    as the carrier, built only from country-specific sets (design Section 6).
    """
    countries = [scope.country] if scope.country else list(peer_sets)
    total_now = total_before = 0.0
    counts: Dict[str, int] = {}
    for country in countries:
        peers = peer_sets.get(country)
        if peers is None or not peers.available:
            continue
        local = frame[frame["country"] == country]
        mean_now, mean_before, n = _country_peer_means(local, peers.members, current, prior)
        if mean_now is None:
            continue
        counts[country] = n
        total_now += mean_now
        total_before += mean_before or 0.0
    if not counts:
        return PeerReference()
    return PeerReference(
        mean_cur=total_now, mean_prior=total_before,
        growth=growth(total_now, total_before),
        sow_cur=share(total_now, marsh_cur), sow_prior=share(total_before, marsh_prior),
        counts=counts,
    )


def slice_metrics(cube: pd.DataFrame, scope: Scope, carrier: str, current: int, prior: int,
                  peer_sets: Mapping[str, PeerSet], *, parent_carrier_cur: Optional[float] = None,
                  mix_parent: str = "") -> SliceMetrics:
    """Every Section 5 metric for one slice of the book."""
    frame = cut(cube, scope)
    now, before = by_carrier(frame, current), by_carrier(frame, prior)
    c_now, c_before = carrier_premium(now, carrier), carrier_premium(before, carrier)
    m_now, m_before = float(now.sum()), float(before.sum())
    rank_now, of_n = dense_rank(now, carrier)
    rank_before, _ = dense_rank(before, carrier)
    return SliceMetrics(
        scope=scope,
        carrier_cur=c_now, carrier_prior=c_before, marsh_cur=m_now, marsh_prior=m_before,
        carrier_growth=growth(c_now, c_before), marsh_growth=growth(m_now, m_before),
        sow_cur=share(c_now, m_now), sow_prior=share(c_before, m_before),
        rank_cur=rank_now, rank_prior=rank_before, rank_of_n=of_n,
        peer=peer_reference(frame, scope, peer_sets, current, prior, m_now, m_before),
        mix_pct=share(c_now, parent_carrier_cur) if parent_carrier_cur else None,
        mix_parent=mix_parent,
    )
