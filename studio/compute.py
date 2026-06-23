"""Deterministic compute orchestration for the Studio pages.

Runs the ``core/analytics`` primitives against the live engine, lands every
``AnalyticsFact`` in a per-session ``FactStore``, applies the rule engine
(truncation), and returns structured page data the renderers consume. No LLM.

This is the "deterministic dispatcher" from DESIGN.md §1 — the registry of cuts
sits behind it; here we drive the breakdown-by-dimension Overall page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.analytics.library import (
    compute_breakdown,
    compute_peer_average_total,
    compute_period_change,
    compute_period_series,
    compute_rank,
    compute_share_of_wallet,
    compute_ttm,
    compute_yoy,
    find_whitespace,
)
from core.analytics.types import PrimitiveArgs
from logger import get_logger
from studio.facts.store import FactStore
from studio.rules import load_rules, truncate

logger = get_logger(__name__)

# Form filter id → real GPR column.
FILTER_COLUMN = {
    "region": "Region",
    "country": "Country",
    "carrier": "Carrier_Group",
    "year": "Year",
    "product_line": "Product_Line",
    "business_line": "Business_Line",
    "cover_line": "Cover_Line",
    "industry": "SIC_Major_Class",
    "sub_industry": "SIC_Minor_Class",
    "client_segment": "Client_Segment",
}
_CARRIER_COL = "Carrier_Group"
_YEAR_COL = "Year"
_INDUSTRY_COL = "SIC_Major_Class"

# Friendly labels for breakdown columns (for section titles).
DIM_LABEL = {
    "SIC_Major_Class": "Industry",
    "Product_Line": "Product Line",
    "Business_Line": "Business Line",
    "Cover_Line": "Cover Line",
    "Client_Segment": "Client Segment",
    "Country": "Country",
    "Region": "Region",
}


@dataclass
class BreakdownSection:
    column: str
    label: str
    rows: List[Dict[str, Any]]          # [{name, premium, sow, yoy}]
    hidden: int = 0


@dataclass
class OverallResult:
    kpis: List[Dict[str, Any]] = field(default_factory=list)
    breakdowns: List[BreakdownSection] = field(default_factory=list)
    whitespace: List[Dict[str, Any]] = field(default_factory=list)
    store: FactStore = field(default_factory=FactStore)
    subject: Optional[str] = None
    # Context the content engine reuses to run movement/period analyses.
    flow: str = "gpr"
    resolved_filters: Dict[str, Any] = field(default_factory=dict)
    engine: Any = None
    # User-pinned custom peer set (Carrier_Group values); None → resolve from Peers table.
    peers: Optional[Tuple[str, ...]] = None


_BLANK_VALS = (None, "", "all", "All")


def _resolve_filters(filters: Mapping[str, Any]) -> Dict[str, Any]:
    """Map non-empty form filters to real columns; drop blanks/'all'.

    Multi-select values (lists from the form) are kept as tuples so they stay
    hashable for ``PrimitiveArgs.cache_key`` and flow through ``where_clause`` as
    an ``IN (...)`` constraint."""
    out: Dict[str, Any] = {}
    for key, val in (filters or {}).items():
        col = FILTER_COLUMN.get(key, key)
        if isinstance(val, (list, tuple, set)):
            vals = [v for v in val if v not in _BLANK_VALS]
            if not vals:
                continue
            if col == _YEAR_COL:
                vals = [int(v) if str(v).isdigit() else v for v in vals]
            out[col] = tuple(vals)
            continue
        if val in _BLANK_VALS:
            continue
        out[col] = int(val) if col == _YEAR_COL and str(val).isdigit() else val
    return out


def _sow_by_dim(flow, dim, filters, engine) -> Dict[str, float]:
    facts = compute_share_of_wallet(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(dim,), filters=filters),
        engine=engine,
    )
    return {str(f.dims.get(dim)): f.value for f in facts}


def _yoy_by_dim(flow, dim, filters_no_year, engine) -> Dict[str, float]:
    """Latest-year YoY % per dim value (computed across years, newest kept)."""
    facts = compute_yoy(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(dim,), filters=filters_no_year),
        engine=engine,
    )
    latest: Dict[str, Tuple[int, float]] = {}
    for f in facts:
        name = str(f.dims.get(dim))
        yr = int(f.dims.get("year", 0) or 0)
        if name not in latest or yr > latest[name][0]:
            latest[name] = (yr, f.value)
    return {k: v for k, (_, v) in latest.items()}


def _breakdown_section(flow, dim, filters, engine, store) -> BreakdownSection:
    facts = compute_breakdown(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(dim,), filters=filters),
        engine=engine,
    )
    store.extend(facts, cut=f"breakdown:{dim}")
    sow = _sow_by_dim(flow, dim, filters, engine)
    filters_no_year = {k: v for k, v in filters.items() if k != _YEAR_COL}
    yoy = _yoy_by_dim(flow, dim, filters_no_year, engine)

    rows = [
        {
            "name": str(f.dims.get(dim)),
            "premium": f.value,
            "sow": sow.get(str(f.dims.get(dim))),
            "yoy": yoy.get(str(f.dims.get(dim))),
        }
        for f in facts
    ]
    trunc = truncate(rows, key=lambda r: r["premium"] or 0.0)
    return BreakdownSection(
        column=dim, label=DIM_LABEL.get(dim, dim), rows=trunc.rows, hidden=trunc.hidden
    )


def _kpis(flow, filters, engine, store, subject) -> List[Dict[str, Any]]:
    from studio.page.format import money

    kpis: List[Dict[str, Any]] = []

    # Total premium.
    total_facts = compute_breakdown(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=filters), engine=engine
    )
    store.extend(total_facts, cut="total")
    total = total_facts[0].value if total_facts else 0.0

    # Total YoY (latest year), computed without the year filter.
    filters_no_year = {k: v for k, v in filters.items() if k != _YEAR_COL}
    yoy_facts = compute_yoy(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=filters_no_year),
        engine=engine,
    )
    store.extend(yoy_facts, cut="total_yoy")
    yoy = max(yoy_facts, key=lambda f: int(f.dims.get("year", 0) or 0)).value if yoy_facts else None

    kpis.append(
        {
            "label": "Total GWP",
            "value": money(total),
            "delta": (f"{yoy:+.1f}% YoY" if yoy is not None else None),
            "tone": "good" if (yoy or 0) >= 0 else "danger",
            "icon": "bi-cash-stack",
        }
    )

    # Subject rank (rank carriers; exclude the carrier filter so the field is full).
    if subject:
        rank_filters = {k: v for k, v in filters.items() if k != _CARRIER_COL}
        rank_facts = compute_rank(
            PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=rank_filters),
            engine=engine,
        )
        store.extend(rank_facts, cut="rank")
        mine = next(
            (f for f in rank_facts if str(f.dims.get("entity", "")).lower() == subject.lower()),
            None,
        )
        if mine:
            kpis.append(
                {"label": "Market Rank", "value": mine.rendered, "tone": "neutral", "icon": "bi-trophy"}
            )

        # Share of Marsh book (subject SoW overall).
        sow_facts = compute_share_of_wallet(
            PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=filters, subject=subject),
            engine=engine,
        )
        store.extend(sow_facts, cut="sow_total")
        if sow_facts:
            kpis.append(
                {
                    "label": "Share of Marsh Book",
                    "value": f"{sow_facts[0].value:.1f}%",
                    "tone": "good",
                    "icon": "bi-pie-chart",
                }
            )
    return kpis


def _whitespace(flow, filters, engine, store) -> List[Dict[str, Any]]:
    cfg = load_rules().whitespace
    facts = find_whitespace(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(_INDUSTRY_COL,), filters=filters),
        engine=engine,
        top_n=cfg.top_n,
        near_zero=cfg.carrier_ceiling,
        material=cfg.material_market_gwp,
    )
    store.extend(facts, cut="whitespace")
    return [{"name": str(f.dims.get(_INDUSTRY_COL)), "market": f.value, "carrier": 0} for f in facts]


# ── insurance-analysis movement helpers (for the QBR content engine) ─────────


def _total(flow, filters, engine) -> float:
    facts = compute_breakdown(PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=filters), engine=engine)
    return facts[0].value if facts else 0.0


def _current_year(filters: Mapping[str, Any]) -> Optional[int]:
    """The reporting year for YoY/movement — the MAX of a multi-select year filter
    (so comparisons run against the latest selected year), or None when unset."""
    yr = filters.get(_YEAR_COL)
    if yr in (None, "", "all", "All"):
        return None
    if isinstance(yr, (list, tuple, set)):
        years = [int(y) for y in yr if str(y).strip().isdigit()]
        return max(years) if years else None
    try:
        return int(yr)
    except (TypeError, ValueError):
        return None


def period_totals(flow, filters, engine) -> Optional[Dict[str, Any]]:
    """Current vs prior-year total premium. None if no year filter is set."""
    cur = _current_year(filters)
    if cur is None:
        return None
    prev = cur - 1
    c = _total(flow, {**filters, _YEAR_COL: cur}, engine)
    p = _total(flow, {**filters, _YEAR_COL: prev}, engine)
    return {"current_year": cur, "prior_year": prev, "current": c, "prior": p,
            "delta": c - p, "pct": ((c - p) / p * 100) if p else None}


def movement_by_dim(flow, dim, filters, engine, *, top: int = 6) -> List[Dict[str, Any]]:
    """Per-dim current vs prior premium + delta — the driver decomposition of YoY."""
    cur = _current_year(filters)
    if cur is None:
        return []
    prev = cur - 1

    def by(year):
        return {str(f.dims.get(dim)): f.value for f in compute_breakdown(
            PrimitiveArgs(flow=flow, metric="premium", group_by=(dim,), filters={**filters, _YEAR_COL: year}),
            engine=engine)}

    c, p = by(cur), by(prev)
    rows = [{"name": n, "current": c.get(n, 0.0), "prior": p.get(n, 0.0),
             "delta": c.get(n, 0.0) - p.get(n, 0.0)} for n in set(c) | set(p)]
    for r in rows:
        r["pct"] = (r["delta"] / r["prior"] * 100) if r["prior"] else None
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return rows[:top]


def rank_movement(flow, filters, engine, subject) -> Optional[Dict[str, Any]]:
    cur = _current_year(filters)
    if cur is None or not subject:
        return None
    prev = cur - 1
    base = {k: v for k, v in filters.items() if k != _CARRIER_COL}

    def rank_at(year):
        facts = compute_rank(PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters={**base, _YEAR_COL: year}), engine=engine)
        m = next((f for f in facts if str(f.dims.get("entity", "")).lower() == subject.lower()), None)
        if not m:
            return None, None
        of_n = m.support[0].get("of_n") if m.support else None
        return int(m.value), (int(of_n) if of_n else None)

    cr, of_n = rank_at(cur)
    pr, _ = rank_at(prev)
    if cr is None:
        return None
    return {"current": cr, "prior": pr, "of_n": of_n,
            "delta": (pr - cr) if (pr is not None) else None}  # +ve delta = improved (moved up)


def sow_movement(flow, filters, engine, subject) -> Optional[Dict[str, Any]]:
    cur = _current_year(filters)
    if cur is None or not subject:
        return None
    prev = cur - 1

    def sow_at(year):
        facts = compute_share_of_wallet(PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters={**filters, _YEAR_COL: year}, subject=subject), engine=engine)
        return facts[0].value if facts else None

    c, p = sow_at(cur), sow_at(prev)
    if c is None:
        return None
    return {"current": c, "prior": p, "delta": (c - p) if (p is not None) else None}


def concentration(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Portfolio concentration: lead share, top-3 share, HHI (0-10000)."""
    vals = sorted((r["premium"] or 0.0 for r in rows), reverse=True)
    total = sum(vals)
    if total <= 0:
        return None
    shares = [v / total for v in vals]
    return {"lead": shares[0] * 100, "top3": sum(shares[:3]) * 100,
            "hhi": round(sum(s * s for s in shares) * 10000), "n": len(vals)}


def peer_gap(flow, filters, engine, peers=None) -> Optional[Dict[str, Any]]:
    """Subject's total premium vs the average peer's TOTAL premium (confidential).

    Like-for-like: the peer benchmark is the mean of each peer carrier's total
    premium in scope (`compute_peer_average_total`), NOT a per-row average — so the
    ratio is meaningful (≈1× means you write about as much as the average peer).
    `peers` pins a custom peer set; None resolves the peer group from the Peers table.
    """
    facts = compute_peer_average_total(
        PrimitiveArgs(
            flow=flow, metric="premium", group_by=(), filters=filters,
            peers=tuple(peers) if peers else None,
        ),
        engine=engine,
    )
    subj = filters.get(_CARRIER_COL)
    if not facts or not subj:
        return None
    peer_avg = facts[0].value
    own = _total(flow, filters, engine)
    return {"peer_avg": peer_avg, "own": own, "n_peers": facts[0].dims.get("peers"),
            "delta": own - peer_avg, "ratio": (own / peer_avg) if peer_avg else None}


def near_rank_gap(flow, filters, engine, subject, *, dim="Product_Line", top=8) -> Optional[Dict[str, Any]]:
    """Gap to the next rank up, decomposed by product line (the rank waterfall).

    Confidentiality: the next-rank carrier is NEVER named — only its rank position
    and the per-product premium gaps are returned."""
    if not subject:
        return None
    base = {k: v for k, v in filters.items() if k != _CARRIER_COL}
    facts = compute_rank(PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=base), engine=engine)
    ranked = sorted(((int(f.value), str(f.dims.get("entity", ""))) for f in facts), key=lambda x: x[0])
    me = next((r for r in ranked if r[1].lower() == subject.lower()), None)
    if not me:
        return None
    cur = me[0]
    target = next((r for r in ranked if r[0] == cur - 1), None)
    if not target:
        return {"current_rank": cur, "target_rank": None, "competitor_rank": None,
                "labels": [], "values": [], "total_gap": 0.0}

    def by_dim(carrier):
        f = {**base, _CARRIER_COL: carrier}
        return {str(x.dims.get(dim)): x.value for x in compute_breakdown(
            PrimitiveArgs(flow=flow, metric="premium", group_by=(dim,), filters=f), engine=engine)}

    mine, theirs = by_dim(subject), by_dim(target[1])
    gaps = [(p, theirs.get(p, 0.0) - mine.get(p, 0.0)) for p in set(mine) | set(theirs)]
    gaps = sorted([(p, g) for p, g in gaps if g > 0], key=lambda kv: kv[1], reverse=True)[:top]
    return {"current_rank": cur, "target_rank": cur - 1, "competitor_rank": target[0],
            "labels": [p for p, _ in gaps], "values": [g for _, g in gaps],
            "total_gap": sum(g for _, g in gaps)}


# ── temporal helpers: TTM / QoQ / MoM (the time-based QBR views) ─────────────


def _temporal_filters(filters: Mapping[str, Any]) -> Dict[str, Any]:
    """Scope filters minus the year, so the time axis spans every available period."""
    return {k: v for k, v in filters.items() if k != _YEAR_COL}


def period_series(flow, filters, engine, *, grain: str = "month") -> Dict[str, Any]:
    """Premium per month/quarter over the full available history (year filter dropped)."""
    facts = compute_period_series(
        PrimitiveArgs(flow=flow, metric="premium", filters=_temporal_filters(filters)),
        grain=grain, engine=engine,
    )
    return {
        "grain": grain,
        "labels": [str(f.dims["period"]) for f in facts],
        "values": [f.value for f in facts],
    }


def period_change(flow, filters, engine, *, grain: str = "month") -> Dict[str, Any]:
    """Period-over-period %: ``grain='month'`` ⇒ MoM, ``grain='quarter'`` ⇒ QoQ."""
    facts = compute_period_change(
        PrimitiveArgs(flow=flow, metric="premium", filters=_temporal_filters(filters)),
        grain=grain, engine=engine,
    )
    labels = [str(f.dims["period"]) for f in facts]
    values = [f.value for f in facts]
    return {
        "grain": grain, "labels": labels, "values": values,
        "latest": values[-1] if values else None,
        "latest_label": labels[-1] if labels else None,
    }


def mom(flow, filters, engine) -> Dict[str, Any]:
    return period_change(flow, filters, engine, grain="month")


def qoq(flow, filters, engine) -> Dict[str, Any]:
    return period_change(flow, filters, engine, grain="quarter")


def ttm(flow, filters, engine) -> Optional[Dict[str, Any]]:
    """Trailing-12-month rolling totals + the headline TTM-over-TTM %."""
    facts = compute_ttm(
        PrimitiveArgs(flow=flow, metric="premium", filters=_temporal_filters(filters)),
        engine=engine,
    )
    if not facts:
        return None
    labels = [str(f.dims["period"]) for f in facts]
    values = [f.value for f in facts]
    ttm_pct = facts[-1].support[0].get("ttm_pct") if facts[-1].support else None
    latest = round((values[-1] - values[-2]) / values[-2] * 100, 1) if (len(values) >= 2 and values[-2]) else None
    return {
        "labels": labels, "values": values,
        "current": values[-1] if values else None,
        "ttm_pct": ttm_pct, "latest": latest,
    }


# ── deterministic data for the advanced widgets (premium / SoW / appetite) ───


def opportunity_matrix(flow, filters, engine, whitespace, *, top_n: Optional[int] = None) -> List[Dict[str, Any]]:
    """Opportunity bubbles from the whitespace candidates — fully premium-derived.

    For each candidate (an industry the market writes materially but the carrier
    barely touches — exactly "max premium in country, carrier negligible"):
      • y (potential) = market GWP, scaled 0–100 across the candidates;
      • x (ease to win) = ``1 − leader's premium share`` in that industry, scaled
        0–100 (a fragmented market with no dominant incumbent is easier to enter);
      • size = market GWP.
    No random values — same inputs always yield the same bubbles.
    """
    if top_n is None:
        top_n = load_rules().opportunity.top_n
    cands = sorted(whitespace or [], key=lambda w: w.get("market", 0) or 0, reverse=True)[:top_n]
    if not cands:
        return []
    max_mkt = max((w["market"] for w in cands), default=0.0) or 1.0
    base = {k: v for k, v in filters.items() if k != _CARRIER_COL}
    points: List[Dict[str, Any]] = []
    for w in cands:
        industry = w["name"]
        carriers = compute_breakdown(
            PrimitiveArgs(flow=flow, metric="premium", group_by=(_CARRIER_COL,),
                          filters={**base, _INDUSTRY_COL: industry}),
            engine=engine,
        )
        vals = sorted((c.value for c in carriers), reverse=True)
        total = sum(vals) or 1.0
        leader_share = (vals[0] / total) if vals else 1.0
        points.append({
            "label": industry,
            "x": round((1 - leader_share) * 100, 1),     # ease to win
            "y": round(w["market"] / max_mkt * 100, 1),  # premium potential
            "size": round(30 + w["market"] / max_mkt * 60, 1),
        })
    return points


def product_country_heatmap(
    flow, filters, engine, *, max_products: int = 6, max_countries: int = 6
) -> Optional[Dict[str, Any]]:
    """Premium across Product Line × Country, normalised 0–100 per cell for colour."""
    facts = compute_breakdown(
        PrimitiveArgs(flow=flow, metric="premium", group_by=("Product_Line", "Country"), filters=filters),
        engine=engine,
    )
    if not facts:
        return None
    cell: Dict[Tuple[str, str], float] = {}
    prods: List[str] = []
    countries: List[str] = []
    for f in facts:
        p, c = str(f.dims.get("Product_Line")), str(f.dims.get("Country"))
        cell[(p, c)] = f.value
        if p not in prods:
            prods.append(p)
        if c not in countries:
            countries.append(c)
    prods = sorted(prods, key=lambda p: sum(cell.get((p, c), 0) for c in countries), reverse=True)[:max_products]
    countries = sorted(countries, key=lambda c: sum(cell.get((p, c), 0) for p in prods), reverse=True)[:max_countries]
    mx = max((cell.get((p, c), 0) for p in prods for c in countries), default=0.0) or 1.0
    values = [[round(cell.get((p, c), 0) / mx * 100) for c in countries] for p in prods]
    return {"rows": prods, "columns": countries, "values": values}


def position_radar(*, totals=None, rankm=None, sowm=None, pg=None, conc=None) -> Optional[Dict[str, Any]]:
    """Competitive-standing radar — each axis 0–100, derived from existing facts.

    Scaling bands are fixed (documented inline) so the chart is deterministic; the
    underlying signals are all premium / rank / share / peer measures.
    """
    labels: List[str] = []
    values: List[float] = []
    if rankm and rankm.get("of_n"):  # #1 of N → 100
        pctile = (1 - (rankm["current"] - 1) / max(rankm["of_n"] - 1, 1)) * 100
        labels.append("Rank"); values.append(round(max(0, min(100, pctile)), 1))
    if sowm and sowm.get("current") is not None:  # share of wallet is already a %
        labels.append("Wallet share"); values.append(round(max(0, min(100, sowm["current"])), 1))
    if totals and totals.get("pct") is not None:  # YoY band −20%..+40% → 0..100
        labels.append("Growth"); values.append(round(max(0, min(100, (totals["pct"] + 20) / 60 * 100)), 1))
    if pg and pg.get("ratio") is not None:  # 0..2× the peer average → 0..100
        labels.append("Vs peers"); values.append(round(max(0, min(100, pg["ratio"] / 2 * 100)), 1))
    if conc and conc.get("top3") is not None:  # diversification = inverse top-3 share
        labels.append("Diversification"); values.append(round(max(0, min(100, 100 - conc["top3"])), 1))
    if len(labels) < 3:
        return None
    return {"labels": labels, "values": values}


def compute_overall(
    *,
    flow: str = "gpr",
    filters: Optional[Mapping[str, Any]] = None,
    breakdowns: Optional[List[str]] = None,
    engine: Any = None,
    peers: Optional[Sequence[str]] = None,
) -> OverallResult:
    """Compute the Overall page from the live DB. Best-effort: a failing metric is
    logged and skipped, never fatal."""
    from studio.data import get_engine

    engine = engine or get_engine()
    resolved = _resolve_filters(filters or {})
    subject = resolved.get(_CARRIER_COL)
    dims = breakdowns or ["Product_Line", _INDUSTRY_COL]
    store = FactStore()
    result = OverallResult(
        store=store, subject=subject, flow=flow, resolved_filters=dict(resolved),
        engine=engine, peers=tuple(peers) if peers else None,
    )

    try:
        result.kpis = _kpis(flow, resolved, engine, store, subject)
    except Exception as exc:  # noqa: BLE001
        logger.warning("studio kpis failed: %s", exc)

    for dim in dims:
        try:
            result.breakdowns.append(_breakdown_section(flow, dim, resolved, engine, store))
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio breakdown %s failed: %s", dim, exc)

    if subject:
        try:
            result.whitespace = _whitespace(flow, resolved, engine, store)
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio whitespace failed: %s", exc)

    return result
