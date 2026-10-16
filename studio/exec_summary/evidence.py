"""MetricEvidence and the store every number in the deck cites (design Sections 13, 17).

Each numerical statement must reference an evidence item carrying the metric name, the
unrounded value, the display value, the period, the unit and the scope. The store hands
out stable ids in insertion order, so the same selection always produces the same ids —
a reproducible run (design Section 21, "Access and reproducibility").
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

from core.analytics.money_units import money_text
from studio.exec_summary.metrics import GROWTH_NA, GROWTH_NEW, Growth, SliceMetrics

UNIT_MONEY = "currency"
UNIT_PCT = "percent"
UNIT_PCT_CHANGE = "percent_change"
UNIT_PP = "percentage_points"
UNIT_RANK = "rank"
UNIT_RANK_MOVE = "rank_movement"
UNIT_SCORE = "score_points"
UNIT_COUNT = "count"

QUALITY_VALID = "valid"


@dataclass(frozen=True)
class MetricEvidence:
    evidence_id: str
    metric_id: str
    scope_id: str
    scope_label: str
    period: str
    value: Optional[float]
    display: str
    unit: str
    prior_value: Optional[float] = None
    quality_status: str = QUALITY_VALID

    def as_dict(self) -> dict:
        return asdict(self)


# ── display formatting (round only at display time — design Section 13) ──────


def money(value: Optional[float], symbol: str = "$") -> str:
    return money_text(value, symbol=symbol)


def _signed(value: float, *, signed: bool) -> str:
    """One decimal, signed when asked; a value that rounds to zero is "0.0", never "-0.0"."""
    shown = round(value, 1)
    if shown == 0:
        return "0.0"
    return f"{shown:+.1f}" if signed else f"{shown:.1f}"


def pct(value: Optional[float], *, signed: bool = False) -> str:
    return "n/a" if value is None else f"{_signed(value, signed=signed)}%"


def points(value: Optional[float]) -> str:
    """A share or growth gap — percentage points, written out (never "pp")."""
    return "n/a" if value is None else f"{_signed(value, signed=True)} percentage points"


def score(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def score_change(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{_signed(value, signed=True)} points"


def growth_display(g: Growth) -> str:
    if g.status == GROWTH_NEW:
        return "new activity"
    if g.status == GROWTH_NA:
        return "not applicable"
    return pct(g.pct, signed=True) if g.valid else "unavailable"


def rank_display(rank: Optional[int]) -> str:
    return "unranked" if rank is None else f"#{rank}"


def rank_move_display(move: Optional[int]) -> str:
    if move is None:
        return "n/a"
    if move == 0:
        return "unchanged"
    return f"up {move}" if move > 0 else f"down {abs(move)}"


class EvidenceStore:
    """An append-only registry of evidence items; ids are ``e1``, ``e2`` … in order."""

    def __init__(self) -> None:
        self._items: Dict[str, MetricEvidence] = {}

    def add(self, metric_id: str, scope_id: str, scope_label: str, period: str,
            value: Optional[float], display: str, unit: str, *,
            prior_value: Optional[float] = None, quality: str = QUALITY_VALID) -> str:
        evidence_id = f"e{len(self._items) + 1}"
        self._items[evidence_id] = MetricEvidence(
            evidence_id, metric_id, scope_id, scope_label, period, value, display, unit,
            prior_value, quality)
        return evidence_id

    def get(self, evidence_id: str) -> Optional[MetricEvidence]:
        return self._items.get(evidence_id)

    def items(self) -> List[MetricEvidence]:
        return list(self._items.values())

    def displays(self, ids: Iterable[str]) -> List[str]:
        return [e.display for e in (self.get(i) for i in ids) if e is not None]

    def __len__(self) -> int:
        return len(self._items)


def add_slice_evidence(store: EvidenceStore, m: SliceMetrics, period: str,
                       symbol: str) -> Dict[str, str]:
    """Register one slice's metrics; returns ``{metric_id: evidence_id}``.

    Only metrics with a value (or an explicit status) are registered, so a payload never
    cites an evidence id whose display is a blank.
    """
    sid, label = m.scope.scope_id, m.scope.label
    ids: Dict[str, str] = {}

    def put(metric: str, value, display: str, unit: str, prior=None) -> None:
        ids[metric] = store.add(metric, sid, label, period, value, display, unit,
                                prior_value=prior)

    put("carrier_premium", m.carrier_cur, money(m.carrier_cur, symbol), UNIT_MONEY,
        m.carrier_prior)
    put("carrier_premium_prior", m.carrier_prior, money(m.carrier_prior, symbol), UNIT_MONEY)
    put("carrier_premium_change", m.carrier_cur - m.carrier_prior,
        money_text(m.carrier_cur - m.carrier_prior, symbol=symbol, signed=True), UNIT_MONEY)
    put("marsh_premium", m.marsh_cur, money(m.marsh_cur, symbol), UNIT_MONEY, m.marsh_prior)
    put("marsh_premium_prior", m.marsh_prior, money(m.marsh_prior, symbol), UNIT_MONEY)
    put("carrier_yoy", m.carrier_growth.pct, growth_display(m.carrier_growth), UNIT_PCT_CHANGE)
    put("marsh_yoy", m.marsh_growth.pct, growth_display(m.marsh_growth), UNIT_PCT_CHANGE)
    if m.sow_cur is not None:
        put("carrier_sow", m.sow_cur, pct(m.sow_cur), UNIT_PCT, m.sow_prior)
    if m.sow_prior is not None:
        put("carrier_sow_prior", m.sow_prior, pct(m.sow_prior), UNIT_PCT)
    if m.sow_change_pp is not None:
        put("sow_change", m.sow_change_pp, points(m.sow_change_pp), UNIT_PP)
    if m.rank_cur is not None:
        put("carrier_rank", m.rank_cur, rank_display(m.rank_cur), UNIT_RANK, m.rank_prior)
    if m.rank_prior is not None:
        put("carrier_rank_prior", m.rank_prior, rank_display(m.rank_prior), UNIT_RANK)
    if m.rank_movement is not None:
        put("rank_movement", m.rank_movement, rank_move_display(m.rank_movement),
            UNIT_RANK_MOVE)
    if m.mix_pct is not None:
        put("portfolio_mix", m.mix_pct, pct(m.mix_pct), UNIT_PCT)
    if m.peer.available:
        put("peer_avg_premium", m.peer.mean_cur, money(m.peer.mean_cur, symbol), UNIT_MONEY,
            m.peer.mean_prior)
        put("peer_avg_yoy", m.peer.growth.pct, growth_display(m.peer.growth), UNIT_PCT_CHANGE)
        if m.peer.sow_cur is not None:
            put("peer_avg_sow", m.peer.sow_cur, pct(m.peer.sow_cur), UNIT_PCT)
    if m.growth_gap_marsh_pp is not None:
        put("growth_gap_vs_marsh", m.growth_gap_marsh_pp, points(m.growth_gap_marsh_pp),
            UNIT_PP)
    if m.growth_gap_peer_pp is not None:
        put("growth_gap_vs_peers", m.growth_gap_peer_pp, points(m.growth_gap_peer_pp), UNIT_PP)
    return ids
