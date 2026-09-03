"""One scope, decomposed into industries and client segments, and what the figures say.

The deck's commentary has always argued from six numbers — premium, YoY, the Marsh book's
YoY, rank, share of wallet and the top-5 peer average — because those are the only numbers
``feedback._facts`` ever produced. Six numbers permute into the same three sentences however
differently a column is briefed, which is why every product page reads alike and why the
Growth column reduces to "closing the 0.1pp gap would add $349K": arithmetic on a rounding
error, offered as an opportunity.

The missing dimension is WHERE inside the scope the book sits. Marsh places $414M of
financial lines in Singapore; the book writes 10.7% of it. That single figure hides the
actual story — across the industries it writes the book runs at 12.9%, ahead of the peer
benchmark in eleven of twelve, and the entire headline deficit is three industries worth
$69M that it does not touch at all. "Placement quality is not the problem, absence is" is a
finding. "You are 0.1pp behind" is not.

This module turns one scope into that decomposition and classifies each row against the
benchmarks a carrier's leadership actually argues from:

    ABSENT   Marsh places materially here and the book writes ~nothing
    LOSING   written, but share given back while the pool moved
    THIN     written below the book's OWN placed average for this scope
    BEHIND   written below the aggregate top-5 peer average
    STRONG   written above its own placed average — the proof the class CAN be placed

``placed_sow`` vs ``scope_sow`` is the load-bearing distinction, and the reason THIN needs
its own baseline. For the line above they are 12.9% and 10.7%; the 2.2 points between them
IS the absence. Measured against ``scope_sow`` a thin industry reads 1.1 points light when
it is really 3.2, and absence hides inside its own average.

Pure and rules-driven, in the shape of its siblings :mod:`studio.posture` and
:mod:`studio.opportunity`: thresholds come from ``rules.yaml``, the predicates are free
functions, and the only IO is one breakdown query per scope-year that everything else is
derived from. It knows nothing about slides, columns or prose.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from core.analytics.library import compute_breakdown
from core.analytics.types import PrimitiveArgs
from logger import get_logger
from studio.rules import load_rules

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_YEAR_COL = "Year"
_INDUSTRY_COL = "SIC_Major_Class"
_SEGMENT_COL = "Client_Segment"
_PEER_TOP_N = 5

# How a dimension is spoken about in prose. The commentary says "industry", never
# "SIC_Major_Class", and the label travels with the finding so no composer has to map
# it back.
DIM_LABEL: Dict[str, str] = {
    _INDUSTRY_COL: "industry",
    _SEGMENT_COL: "client segment",
    "Product_Line": "line",
}


class Placement(str, Enum):
    """What one decomposed row's figures say about the book's position in it."""

    ABSENT = "absent"
    LOSING = "losing"
    THIN = "thin"
    BEHIND = "behind"
    STRONG = "strong"
    TRACKING = "tracking"      # nothing here worth a sentence


# A top-THREE share only says something when there are meaningfully more than three groups
# to concentrate into. Client segment has exactly three values, so its top three always
# carry 100% -- true, arithmetic, and worthless on a slide.
_MIN_GROUPS_FOR_CONCENTRATION = 6

# The opportunity kinds, in the order the Growth column argues them: what the book does not
# write at all, then what it writes below its own standard, then what it writes below the
# benchmark. Exported so no composer re-declares the order.
OPPORTUNITY_KINDS: Tuple[Placement, ...] = (
    Placement.ABSENT, Placement.THIN, Placement.BEHIND,
)


@dataclass(frozen=True)
class Thresholds:
    """Every rule this module applies, flattened from the three ``rules.yaml`` blocks it
    reads (``segments``, ``whitespace``, ``materiality``). Passed explicitly into the
    predicates so a test can move one threshold without touching the YAML."""

    min_market: float = 5_000_000.0            # materiality.min_premium_for_industry_commentary
    carrier_ceiling: float = 0.0               # whitespace.carrier_ceiling
    material_market_gwp: float = 5_000_000.0   # whitespace.material_market_gwp
    min_carriers: int = 3
    thin_share_margin: float = 2.0
    behind_peer_margin: float = 1.0
    strong_share_margin: float = 2.0
    losing_share_move: float = 1.0
    deviation_pp: float = 1.5
    peer_top_n: int = _PEER_TOP_N


def thresholds() -> Thresholds:
    """The rules as configured. A parse miss yields the coded defaults, never an error —
    the contract every block in :mod:`studio.rules.engine` already keeps."""
    cfg = load_rules()
    seg, ws, mat = cfg.segments, cfg.whitespace, cfg.materiality
    return Thresholds(
        min_market=mat.min_premium_for_industry_commentary,
        carrier_ceiling=ws.carrier_ceiling,
        material_market_gwp=ws.material_market_gwp,
        min_carriers=seg.min_carriers,
        thin_share_margin=seg.thin_share_margin,
        behind_peer_margin=seg.behind_peer_margin,
        strong_share_margin=seg.strong_share_margin,
        losing_share_move=seg.losing_share_move,
        deviation_pp=seg.deviation_pp,
    )


def configured_dims() -> Tuple[str, ...]:
    """The decompositions commentary may use — a config change, not a code change."""
    return tuple(load_rules().segments.dims)


def usable_dims(flow: str, dims: Sequence[str] = ()) -> Tuple[str, ...]:
    """Of ``dims``, the ones THIS flow can actually decompose by.

    The configured dimensions are premium-book columns. A survey deck has no premium and
    no ``SIC_Major_Class``, so asking for either raises inside the primitive and the whole
    decomposition is logged as unavailable — twice per scope, on every page of a run that
    was never going to have industries. Checking the registry first turns that noise back
    into what it is: a flow this analysis does not apply to.
    """
    wanted = tuple(dims) if dims else configured_dims()
    try:
        from core.analytics.sql import find_metric, flow_spec

        spec = flow_spec(flow)
        if find_metric(spec, "premium") is None:
            return ()
        return tuple(d for d in wanted if d in (spec.columns or {}))
    except Exception as exc:  # noqa: BLE001 — an unknown flow is not a reason to raise
        logger.debug("segments: cannot check dimensions for flow %r (%s)", flow, exc)
        return wanted


# ── the contracts ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SegmentFinding:
    """One industry or client-segment row inside a scope, and its classification."""

    dim: str                              # "SIC_Major_Class" | "Client_Segment"
    name: str                             # "Renewable Energy"
    carrier: float = 0.0                  # carrier premium here, reporting year
    market: float = 0.0                   # Marsh premium here, all carriers
    sow: Optional[float] = None           # carrier / market * 100
    placed_sow: Optional[float] = None    # the book's average share where it DOES write
    peer_sow: Optional[float] = None      # top-5 carrier AVERAGE premium / market * 100
    yoy: Optional[float] = None           # carrier premium movement, %
    market_yoy: Optional[float] = None    # Marsh premium movement, %
    sow_delta: Optional[float] = None     # share movement, percentage points
    carriers: int = 0                     # how many carriers Marsh placed with here
    placement: Placement = Placement.TRACKING

    @property
    def label(self) -> str:
        return DIM_LABEL.get(self.dim, "segment")

    @property
    def unwritten(self) -> float:
        """Marsh premium here that went to someone else."""
        return max(self.market - self.carrier, 0.0)

    @property
    def benchmark(self) -> Optional[float]:
        """The share this row is judged against — the peer average for BEHIND, the book's
        own placed average otherwise. Named so a sentence can quote the comparison made."""
        if self.placement is Placement.BEHIND:
            return self.peer_sow
        return self.placed_sow

    @property
    def stake(self) -> float:
        """The premium this finding puts in play — the ONE key every kind ranks on.

        Absence stakes the whole pool; a shortfall stakes the premium between here and the
        benchmark; a decline stakes what was given back; a strength stakes what is held.
        One comparable number is what lets the Growth column rank three different kinds of
        opportunity against each other rather than listing them by type.
        """
        if self.placement is Placement.ABSENT:
            return self.market
        if self.placement in (Placement.THIN, Placement.BEHIND):
            gap = (self.benchmark or 0.0) - (self.sow or 0.0)
            return self.market * max(gap, 0.0) / 100.0
        if self.placement is Placement.LOSING:
            return self.market * abs(self.sow_delta or 0.0) / 100.0
        if self.placement is Placement.STRONG:
            return self.carrier
        return 0.0


@dataclass(frozen=True)
class SegmentFindings:
    """One dimension's decomposition of one scope, ranked by premium at stake."""

    dim: str = ""
    label: str = ""
    scope_sow: Optional[float] = None     # share across the WHOLE scope, absences included
    placed_sow: Optional[float] = None    # share across the values the book actually writes
    rows: Tuple[SegmentFinding, ...] = ()

    def of(self, *placements: Placement) -> Tuple[SegmentFinding, ...]:
        """The rows of these kinds, most premium at stake first."""
        wanted = set(placements)
        return tuple(sorted((r for r in self.rows if r.placement in wanted),
                            key=lambda r: r.stake, reverse=True))

    def best(self, *placements: Placement) -> Optional[SegmentFinding]:
        rows = self.of(*placements)
        return rows[0] if rows else None

    def proof(self) -> Optional[SegmentFinding]:
        """Where the book places best — the evidence the class CAN be written better."""
        return self.best(Placement.STRONG)

    def named(self, name: str) -> Optional[SegmentFinding]:
        return next((r for r in self.rows if r.name == name), None)

    @property
    def written(self) -> Tuple[SegmentFinding, ...]:
        """The values the book actually writes, largest first."""
        return tuple(sorted((r for r in self.rows if r.carrier > 0),
                            key=lambda r: r.carrier, reverse=True))

    @property
    def top3_share(self) -> Optional[float]:
        """How much of the book its three largest values carry, as a percent.

        ``None`` when there are too few values for the answer to mean anything: the top
        three of three is always 100%, which is arithmetic rather than a finding.
        """
        written = self.written
        if len(written) < _MIN_GROUPS_FOR_CONCENTRATION:
            return None
        total = sum(r.carrier for r in written)
        return (sum(r.carrier for r in written[:3]) / total * 100.0) if total else None

    @property
    def absent_total(self) -> float:
        return sum(r.market for r in self.of(Placement.ABSENT))

    @property
    def absent_count(self) -> int:
        return len(self.of(Placement.ABSENT))

    def __bool__(self) -> bool:
        return bool(self.rows)


# ── the predicates (pure) ───────────────────────────────────────────────────


def is_absent(f: SegmentFinding, cfg: Thresholds) -> bool:
    """Marsh places materially here and the book writes at or below the whitespace floor.

    Deliberately the same rule ``core.analytics.find_whitespace`` already applies, on the
    same ``whitespace:`` thresholds — one definition of a gap, wherever it is asked for.
    """
    return f.market >= cfg.material_market_gwp and f.carrier <= cfg.carrier_ceiling


def is_losing(f: SegmentFinding, cfg: Thresholds) -> bool:
    """Share given back here, by enough to be a movement rather than rounding."""
    return (f.market >= cfg.min_market and f.sow_delta is not None
            and f.sow_delta <= -cfg.losing_share_move)


def is_thin(f: SegmentFinding, cfg: Thresholds) -> bool:
    """Written, but below the book's own standard — the benchmark it cannot argue with."""
    return (f.market >= cfg.min_market and f.carrier > cfg.carrier_ceiling
            and f.sow is not None and f.placed_sow is not None
            and f.placed_sow - f.sow >= cfg.thin_share_margin)


def is_behind(f: SegmentFinding, cfg: Thresholds) -> bool:
    """Below the aggregate top-5 peer average.

    ``min_carriers`` is a confidentiality rule, not a statistical one: with two carriers in
    a segment the "top-5 average" IS one peer's number, which ``peer.aggregate_only``
    forbids the deck from disclosing.
    """
    return (f.market >= cfg.min_market and f.carrier > cfg.carrier_ceiling
            and f.sow is not None and f.peer_sow is not None
            and f.carriers >= cfg.min_carriers
            and f.peer_sow - f.sow >= cfg.behind_peer_margin)


def is_strong(f: SegmentFinding, cfg: Thresholds) -> bool:
    """Above its own placed average, and not behind the benchmark — the proof point."""
    return (f.market >= cfg.min_market and f.sow is not None and f.placed_sow is not None
            and f.sow - f.placed_sow >= cfg.strong_share_margin
            and (f.peer_sow is None or f.sow >= f.peer_sow))


# First test that holds decides. ABSENT leads because a book at zero cannot be thin or
# losing. LOSING precedes THIN because share being given back is the live event and the
# level is its context. THIN precedes BEHIND because the book's own average is the more
# defensible benchmark and needs no peer set at all. STRONG is last, the only positive.
_TESTS: Tuple[Tuple[Placement, Callable[[SegmentFinding, Thresholds], bool]], ...] = (
    (Placement.ABSENT, is_absent),
    (Placement.LOSING, is_losing),
    (Placement.THIN, is_thin),
    (Placement.BEHIND, is_behind),
    (Placement.STRONG, is_strong),
)


def classify(f: SegmentFinding, cfg: Thresholds) -> Placement:
    """The one class this row's figures earn."""
    return next((p for p, test in _TESTS if test(f, cfg)), Placement.TRACKING)


# ── the one query everything is derived from ────────────────────────────────


def _filters_key(filters: Mapping[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    """Filters as a hashable, order-independent cache key (multi-selects as tuples)."""
    out: List[Tuple[str, Any]] = []
    for col, val in sorted((filters or {}).items()):
        if isinstance(val, (list, tuple, set)):
            out.append((col, tuple(sorted(str(v) for v in val))))
        else:
            out.append((col, val))
    return tuple(out)


@lru_cache(maxsize=512)
def _premium_by_carrier(flow: str, dim: str, key: Tuple[Tuple[str, Any], ...],
                        engine: Any) -> Tuple[Tuple[str, str, float], ...]:
    """``(segment, carrier, premium)`` for one scope-year — the ONE query this module runs.

    Market total, the subject's own premium, the top-5 peer average and the carrier count
    all fall out of this single grouped breakdown, so a scope costs two queries (this year
    and last) per dimension rather than one per figure.

    Cached because three separate callers ask for the same scope on one deck:
    ``feedback.values`` per country row, ``commentary.panel_facts``, and
    ``stance.portfolio_extras``. The warehouse is static within a process, which is the
    same assumption ``studio.data`` and ``binding_map`` already cache on; a long-lived
    process that reloads its data must clear this (:func:`reset_cache`).
    """
    filters = {col: (list(val) if isinstance(val, tuple) else val) for col, val in key}
    facts = compute_breakdown(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(dim, _CARRIER_COL),
                      filters=filters),
        engine=engine,
    )
    return tuple(
        (str(f.dims.get(dim)), str(f.dims.get(_CARRIER_COL)), float(f.value or 0.0))
        for f in facts
        if f.dims.get(dim) is not None and f.dims.get(_CARRIER_COL) is not None
    )


def reset_cache() -> None:
    """Forget every cached breakdown — for tests, and for a process that reloads data."""
    _premium_by_carrier.cache_clear()


def _top_average(values: Sequence[float], *, top: int = _PEER_TOP_N) -> float:
    """Mean of the ``top`` largest values — the peer benchmark, never a named carrier.

    Identical to :func:`studio.compute._top_average` so the per-segment peer share is
    computed on exactly the same basis as the scope-level one the KPI band already shows.
    """
    head = sorted((v or 0.0 for v in values), reverse=True)[:top]
    return (sum(head) / len(head)) if head else 0.0


@dataclass(frozen=True)
class _Slice:
    """One dimension value in one year, before it is compared with anything."""

    market: float = 0.0
    carrier: float = 0.0
    peer: float = 0.0
    carriers: int = 0


def _slices(flow: str, dim: str, filters: Mapping[str, Any], engine: Any, *,
            subject: str, year: Optional[int], top: int) -> Dict[str, _Slice]:
    """Every dimension value in one year: market, the subject's own, the peer average."""
    scoped = {k: v for k, v in (filters or {}).items() if k != _CARRIER_COL}
    if year is not None:
        scoped[_YEAR_COL] = year
    rows = _premium_by_carrier(flow, dim, _filters_key(scoped), engine)

    by_segment: Dict[str, Dict[str, float]] = defaultdict(dict)
    for segment, carrier, premium in rows:
        by_segment[segment][carrier] = by_segment[segment].get(carrier, 0.0) + premium

    low = (subject or "").strip().lower()
    out: Dict[str, _Slice] = {}
    for segment, carriers in by_segment.items():
        values = list(carriers.values())
        mine = next((v for c, v in carriers.items() if c.strip().lower() == low), 0.0)
        out[segment] = _Slice(market=sum(values), carrier=mine,
                              peer=_top_average(values, top=top), carriers=len(values))
    return out


# ── assembly ────────────────────────────────────────────────────────────────


def _share(part: float, whole: float) -> Optional[float]:
    return (part / whole * 100.0) if whole else None


def _movement(now: float, before: float) -> Optional[float]:
    return ((now - before) / before * 100.0) if before else None


def _placed_share(slices: Mapping[str, _Slice], cfg: Thresholds) -> Optional[float]:
    """The book's share across the values it ACTUALLY writes.

    The scope's own average is dragged down by every segment the book is absent from, so
    measuring a thin segment against it understates the shortfall and hides the absence
    inside it. This is the benchmark THIN and STRONG are judged on.
    """
    written = [s for s in slices.values() if s.carrier > cfg.carrier_ceiling]
    return _share(sum(s.carrier for s in written), sum(s.market for s in written))


def _finding(dim: str, name: str, now: _Slice, before: Optional[_Slice],
             placed_sow: Optional[float], cfg: Thresholds) -> SegmentFinding:
    """One row, measured and classified. Pure — everything it needs is an argument."""
    sow = _share(now.carrier, now.market)
    prior_sow = _share(before.carrier, before.market) if before else None
    row = SegmentFinding(
        dim=dim, name=name, carrier=now.carrier, market=now.market,
        sow=sow, placed_sow=placed_sow,
        peer_sow=_share(now.peer, now.market),
        yoy=_movement(now.carrier, before.carrier) if before else None,
        market_yoy=_movement(now.market, before.market) if before else None,
        sow_delta=None if (sow is None or prior_sow is None) else sow - prior_sow,
        carriers=now.carriers,
    )
    from dataclasses import replace

    return replace(row, placement=classify(row, cfg))


def find_segments(*, flow: str, filters: Mapping[str, Any], engine: Any, subject: str,
                  dim: str = _INDUSTRY_COL, year: Optional[int] = None,
                  cfg: Optional[Thresholds] = None) -> SegmentFindings:
    """Decompose one scope by ``dim`` and classify every value in it.

    ``year`` is the reporting year; the prior year is fetched alongside it so a row can
    carry movement as well as level. Without a year the scope is measured as it stands and
    LOSING can never fire, which is correct rather than silently wrong.
    """
    cfg = cfg or thresholds()
    now = _slices(flow, dim, filters, engine, subject=subject, year=year, top=cfg.peer_top_n)
    if not now:
        return SegmentFindings(dim=dim, label=DIM_LABEL.get(dim, "segment"))
    before = (_slices(flow, dim, filters, engine, subject=subject, year=year - 1,
                      top=cfg.peer_top_n) if year is not None else {})

    placed_sow = _placed_share(now, cfg)
    rows = tuple(
        _finding(dim, name, slice_, before.get(name), placed_sow, cfg)
        for name, slice_ in sorted(now.items())
    )
    return SegmentFindings(
        dim=dim,
        label=DIM_LABEL.get(dim, "segment"),
        scope_sow=_share(sum(s.carrier for s in now.values()),
                         sum(s.market for s in now.values())),
        placed_sow=placed_sow,
        rows=tuple(sorted(rows, key=lambda r: r.stake, reverse=True)),
    )


def find_all(*, flow: str, filters: Mapping[str, Any], engine: Any, subject: str,
             dims: Sequence[str] = (), year: Optional[int] = None,
             cfg: Optional[Thresholds] = None) -> Dict[str, SegmentFindings]:
    """Every configured decomposition of one scope, keyed by dimension column."""
    cfg = cfg or thresholds()
    out: Dict[str, SegmentFindings] = {}
    for dim in usable_dims(flow, dims):
        try:
            found = find_segments(flow=flow, filters=filters, engine=engine, subject=subject,
                                  dim=dim, year=year, cfg=cfg)
        except Exception as exc:  # noqa: BLE001 — a decomposition sharpens a column, never gates it
            logger.warning("segments: %s decomposition unavailable (%s)", dim, exc)
            continue
        if found:
            out[dim] = found
    return out


# ── altitude: which scope a finding belongs to ──────────────────────────────


def distinguish(child: SegmentFindings, parent: Optional[SegmentFindings],
                cfg: Optional[Thresholds] = None) -> Tuple[SegmentFinding, ...]:
    """The child's findings that its PARENT does not already make.

    Without this every page independently rediscovers the same portfolio-wide fact: the
    three industries this book writes none of are absent in all four of its markets, so a
    four-country deck would print Renewable Energy eleven times. ``ClaimLedger`` would
    suppress the copies, but by first-render-wins — an arbitrary page keeps the claim and
    the rest silently fall to a weaker one.

    A finding stays with the child only when the child's share there departs from the
    parent's by more than ``deviation_pp``. Everything else belongs one level up, said
    once. An empty result is the legitimate answer "this scope tracks its parent", not a
    failure — :func:`tracks` is how a caller asks.
    """
    cfg = cfg or thresholds()
    if parent is None or not parent:
        return child.rows
    out: List[SegmentFinding] = []
    for row in child.rows:
        above = parent.named(row.name)
        if above is None or above.sow is None or row.sow is None:
            out.append(row)
            continue
        if abs(row.sow - above.sow) >= cfg.deviation_pp:
            out.append(row)
    return tuple(out)


def tracks(child: SegmentFindings, parent: Optional[SegmentFindings],
           cfg: Optional[Thresholds] = None) -> bool:
    """True when nothing about this scope's shape differs from its parent's.

    Worth saying out loud on the slide. "The industry mix tracks the portfolio" tells a
    leadership team there is no local anomaly to chase, which is a real finding; inventing
    a difference to fill the column is how the deck currently reads.
    """
    return parent is not None and bool(parent) and not distinguish(child, parent, cfg)


def narrow(child: Mapping[str, SegmentFindings],
           parent: Mapping[str, SegmentFindings],
           cfg: Optional[Thresholds] = None,
           ) -> Tuple[Dict[str, SegmentFindings], bool]:
    """Keep only what makes this scope different from its parent, and say whether anything does.

    Returns ``(narrowed, tracks)``. ``tracks`` is True when the child HAD findings and none
    of them survived — the honest "this scope behaves like the portfolio" answer, which is
    worth a sentence of its own rather than an empty column.

    Without this every page recomputes the same portfolio-wide facts and prints them: the
    three industries this book writes none of are absent in all four markets and all six
    lines, so all twenty-four product pages opened their Growth column on Renewable Energy.
    ``ClaimLedger`` cannot catch that, because each page renders a different premium figure
    and so a different string.
    """
    from dataclasses import replace

    cfg = cfg or thresholds()
    out: Dict[str, SegmentFindings] = {}
    had = False
    for dim, found in child.items():
        if found.rows:
            had = True
        kept = distinguish(found, parent.get(dim), cfg)
        if kept:
            out[dim] = replace(found, rows=kept)
    return out, (had and not out)


def pick_cut(cuts: Mapping[str, SegmentFindings],
             parents: Optional[Mapping[str, SegmentFindings]] = None,
             cfg: Optional[Thresholds] = None) -> Optional[str]:
    """The dimension this scope departs from its parent on furthest — what makes it itself.

    Selection is by deviation rather than by page type on purpose. "Industry on product
    pages, product on country pages" is right only on data that happens to behave; on a
    book whose industry mix is uniform across markets it prints the same sentence on every
    page. Ranking the cuts by how much they distinguish THIS scope surfaces industry where
    industry is the story and segment where it is not.
    """
    cfg = cfg or thresholds()
    parents = parents or {}

    def reach(dim: str, found: SegmentFindings) -> float:
        rows = distinguish(found, parents.get(dim), cfg)
        return max((r.stake for r in rows), default=0.0)

    ranked = sorted(((reach(dim, found), dim) for dim, found in cuts.items()), reverse=True)
    return next((dim for stake, dim in ranked if stake > 0), None)
