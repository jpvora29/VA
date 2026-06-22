"""Deterministic compute orchestration for the Studio pages.

Runs the ``core/analytics`` primitives against the live engine, lands every
``AnalyticsFact`` in a per-session ``FactStore``, applies the rule engine
(truncation), and returns structured page data the renderers consume. No LLM.

This is the "deterministic dispatcher" from DESIGN.md §1 — the registry of cuts
sits behind it; here we drive the breakdown-by-dimension Overall page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from core.analytics.library import (
    compute_breakdown,
    compute_peer_average,
    compute_rank,
    compute_share_of_wallet,
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


def _resolve_filters(filters: Mapping[str, Any]) -> Dict[str, Any]:
    """Map non-empty form filters to real columns; drop blanks/'all'."""
    out: Dict[str, Any] = {}
    for key, val in (filters or {}).items():
        col = FILTER_COLUMN.get(key, key)
        if val in (None, "", "all", "All"):
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


def period_totals(flow, filters, engine) -> Optional[Dict[str, Any]]:
    """Current vs prior-year total premium. None if no year filter is set."""
    yr = filters.get(_YEAR_COL)
    if not yr:
        return None
    cur, prev = int(yr), int(yr) - 1
    c = _total(flow, {**filters, _YEAR_COL: cur}, engine)
    p = _total(flow, {**filters, _YEAR_COL: prev}, engine)
    return {"current_year": cur, "prior_year": prev, "current": c, "prior": p,
            "delta": c - p, "pct": ((c - p) / p * 100) if p else None}


def movement_by_dim(flow, dim, filters, engine, *, top: int = 6) -> List[Dict[str, Any]]:
    """Per-dim current vs prior premium + delta — the driver decomposition of YoY."""
    yr = filters.get(_YEAR_COL)
    if not yr:
        return []
    cur, prev = int(yr), int(yr) - 1

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
    yr = filters.get(_YEAR_COL)
    if not yr or not subject:
        return None
    cur, prev = int(yr), int(yr) - 1
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
    yr = filters.get(_YEAR_COL)
    if not yr or not subject:
        return None
    cur, prev = int(yr), int(yr) - 1

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


def peer_gap(flow, filters, engine) -> Optional[Dict[str, Any]]:
    """Subject's premium vs the aggregate peer average (confidential: no peer names)."""
    facts = compute_peer_average(PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=filters), engine=engine)
    subj = filters.get(_CARRIER_COL)
    if not facts or not subj:
        return None
    peer_avg = facts[0].value
    own = _total(flow, filters, engine)
    return {"peer_avg": peer_avg, "own": own, "delta": own - peer_avg,
            "ratio": (own / peer_avg) if peer_avg else None}


def compute_overall(
    *,
    flow: str = "gpr",
    filters: Optional[Mapping[str, Any]] = None,
    breakdowns: Optional[List[str]] = None,
    engine: Any = None,
) -> OverallResult:
    """Compute the Overall page from the live DB. Best-effort: a failing metric is
    logged and skipped, never fatal."""
    from studio.data import get_engine

    engine = engine or get_engine()
    resolved = _resolve_filters(filters or {})
    subject = resolved.get(_CARRIER_COL)
    dims = breakdowns or ["Product_Line", _INDUSTRY_COL]
    store = FactStore()
    result = OverallResult(store=store, subject=subject, flow=flow, resolved_filters=dict(resolved), engine=engine)

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
