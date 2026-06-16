"""The deterministic analytics primitive library (Phase 2).

Each primitive encodes a known recipe (see ``core/rules/gpr.py`` /
``core/rules/survey.py``) as a tested, parametrized query over the SQLite DB,
returning provenance-bearing `AnalyticsFact`s. Aggregation is pushed down to
SQLite; Python only shapes the result. None of the numbers are LLM-generated.

Tiers (see the plan):
  - Tier 1 atomic: `compute_breakdown`, `compute_rank`, `compute_yoy`
    (shared, flow-agnostic); `compute_share_of_portfolio`, `compute_market_presence`
    (GPR premium domain).
  - Tier 2 composite: `find_whitespace` — composes tier-1 primitives and owns ONLY
    the gap rule (no peer/market math of its own).

Primitives take an injected SQLAlchemy `engine` (defaulting lazily to the process
engine), so they unit-test against an in-memory DB. They are NOT yet wired into
the live app or the registry — that is Phase 3.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from core.analytics.sql import (
    flow_spec,
    resolve_engine,
    resolve_measure,
    run_rows,
    safe_column,
    where_clause,
)
from core.analytics.types import AnalyticsFact, PrimitiveArgs


def _num(value: Any) -> float:
    """Coerce a possibly-null SQL aggregate to a float."""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _cut_columns(spec, group_by) -> List[str]:
    return [safe_column(spec, c) for c in group_by]


def _measure_by_cut(
    spec, engine, *, column: str, agg: str, group_by, filters: Dict[str, Any]
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """SELECT agg(measure) per group_by cut — the shared aggregation core."""
    cuts = _cut_columns(spec, group_by)
    params: Dict[str, Any] = {}
    where = where_clause(spec, filters, params)
    cut_sel = ", ".join(f'"{c}"' for c in cuts)
    select = (cut_sel + ", " if cut_sel else "") + f'{agg}("{column}") AS value'
    group = f" GROUP BY {cut_sel}" if cut_sel else ""
    sql = f'SELECT {select} FROM "{spec.primary_table}"{where}{group} ORDER BY value DESC'
    return cuts, run_rows(engine, sql, params)


# ── Tier 1 — atomic, shared ────────────────────────────────────────────────

def compute_breakdown(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """The measure (premium/score) per group_by cut, under the given filters."""
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric)
    cuts, rows = _measure_by_cut(
        spec, eng, column=column, agg=agg, group_by=args.group_by, filters=args.filters
    )
    return [
        AnalyticsFact(
            name="breakdown",
            value=_num(row["value"]),
            unit=column,
            rendered=f'{_num(row["value"]):,.1f}',
            dims={c: row[c] for c in cuts},
            support=[row],
            formula=f'{agg}({column}) by {", ".join(cuts) or "all"}',
        )
        for row in rows
    ]


def compute_rank(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """Rank entities (carriers) by the measure, within each group_by cut."""
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric)
    entity = spec.entity_columns.get("carrier")
    cuts = _cut_columns(spec, args.group_by)
    params: Dict[str, Any] = {}
    where = where_clause(spec, args.filters, params)
    cut_sel = ", ".join(f'"{c}"' for c in cuts)
    group_cols = ", ".join([f'"{entity}"'] + [f'"{c}"' for c in cuts])
    partition = f"PARTITION BY {cut_sel} " if cut_sel else ""
    count_over = f"PARTITION BY {cut_sel}" if cut_sel else ""
    sql = f"""
        WITH agg AS (
            SELECT "{entity}" AS entity{", " + cut_sel if cut_sel else ""},
                   {agg}("{column}") AS measure
            FROM "{spec.primary_table}"{where}
            GROUP BY {group_cols}
        )
        SELECT *, RANK() OVER ({partition}ORDER BY measure DESC) AS rank,
                  COUNT(*) OVER ({count_over}) AS of_n
        FROM agg
        ORDER BY {(cut_sel + ", ") if cut_sel else ""}rank
    """
    rows = run_rows(eng, sql, params)
    facts: List[AnalyticsFact] = []
    for row in rows:
        dims = {"entity": row["entity"], **{c: row[c] for c in cuts}}
        facts.append(
            AnalyticsFact(
                name="rank",
                value=int(row["rank"]),
                unit="rank",
                rendered=f'#{int(row["rank"])} of {int(row["of_n"])}',
                dims=dims,
                support=[row],
                formula=f"RANK() over {agg}({column}) desc",
            )
        )
    return facts


def compute_yoy(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """Year-over-year % change of the measure, per group_by cut.

    YoY = (current - prior) / prior * 100. Emits a fact only for periods that
    have a prior year (the first year has no YoY).
    """
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric)
    year = spec.date_columns.get("year")
    cuts = _cut_columns(spec, args.group_by)
    params: Dict[str, Any] = {}
    where = where_clause(spec, args.filters, params)
    cut_sel = ", ".join(f'"{c}"' for c in cuts)
    group_cols = ", ".join([f'"{year}"'] + [f'"{c}"' for c in cuts])
    partition = f"PARTITION BY {cut_sel} " if cut_sel else ""
    sql = f"""
        WITH agg AS (
            SELECT "{year}" AS yr{", " + cut_sel if cut_sel else ""},
                   {agg}("{column}") AS measure
            FROM "{spec.primary_table}"{where}
            GROUP BY {group_cols}
        )
        SELECT *, LAG(measure) OVER ({partition}ORDER BY yr) AS prev
        FROM agg
        ORDER BY yr
    """
    rows = run_rows(eng, sql, params)
    facts: List[AnalyticsFact] = []
    for row in rows:
        prev = row.get("prev")
        if prev in (None, 0) or _num(prev) == 0.0:
            continue
        pct = round((_num(row["measure"]) - _num(prev)) / _num(prev) * 100, 1)
        dims = {"year": row["yr"], **{c: row[c] for c in cuts}}
        facts.append(
            AnalyticsFact(
                name="yoy",
                value=pct,
                unit="%",
                rendered=f"{pct:+.1f}%",
                dims=dims,
                support=[row],
                formula="(current - prior) / prior * 100, by year",
            )
        )
    return facts


# ── Tier 1 — atomic, GPR premium domain ────────────────────────────────────

def compute_share_of_portfolio(
    args: PrimitiveArgs, *, engine: Optional[Any] = None
) -> List[AnalyticsFact]:
    """Share of Portfolio (Appetite): each cut's premium as a % of the carrier's
    own book — the exact recipe in ``core/rules/gpr.py``."""
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, _ = resolve_measure(spec, args.metric or "premium")
    carrier = spec.entity_columns.get("carrier")
    cuts = _cut_columns(spec, args.group_by)
    params: Dict[str, Any] = {}
    where = where_clause(spec, args.filters, params)
    cut_sel = ", ".join(f'"{c}"' for c in cuts)
    group_cols = ", ".join([f'"{carrier}"'] + [f'"{c}"' for c in cuts])
    sql = f"""
        SELECT "{carrier}" AS carrier{", " + cut_sel if cut_sel else ""},
               SUM("{column}") AS carrier_premium,
               ROUND(100.0 * SUM("{column}")
                     / NULLIF(SUM(SUM("{column}")) OVER (PARTITION BY "{carrier}"), 0), 1) AS sop_pct
        FROM "{spec.primary_table}"{where}
        GROUP BY {group_cols}
        ORDER BY sop_pct DESC
    """
    rows = run_rows(eng, sql, params)
    return [
        AnalyticsFact(
            name="share_of_portfolio",
            value=_num(row["sop_pct"]),
            unit="%",
            rendered=f'{_num(row["sop_pct"]):.1f}%',
            dims={"carrier": row["carrier"], **{c: row[c] for c in cuts}},
            support=[row],
            formula="SUM(Premium) per cut / carrier total Premium * 100",
        )
        for row in rows
    ]


def compute_market_presence(
    args: PrimitiveArgs, *, engine: Optional[Any] = None
) -> List[AnalyticsFact]:
    """Marsh/market premium per cut: total premium under all filters EXCEPT the
    carrier filter — the context a whitespace gap is measured against."""
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric or "premium")
    carrier = spec.entity_columns.get("carrier")
    filters = {k: v for k, v in args.filters.items() if k != carrier}
    cuts, rows = _measure_by_cut(
        spec, eng, column=column, agg=agg, group_by=args.group_by, filters=filters
    )
    return [
        AnalyticsFact(
            name="market_presence",
            value=_num(row["value"]),
            unit=column,
            rendered=f'{_num(row["value"]):,.1f}',
            dims={c: row[c] for c in cuts},
            support=[row],
            formula=f"{agg}({column}) per cut, carrier filter excluded",
        )
        for row in rows
    ]


def compute_peer_average(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """The peer group's average of the measure, per group_by cut.

    Resolves the subject's peer set from the flow's Peers table (registry
    `peer_columns`), then aggregates the measure over those peers — peer AVERAGE
    only, never individual peers (the survey rule). The subject's own carrier
    filter is dropped so the result is the peers, not the subject.
    """
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    peer = spec.peer_columns
    carrier_col = spec.entity_columns.get("carrier")
    subject = args.subject or args.filters.get(carrier_col)
    if not peer or not carrier_col or not subject:
        return []

    # Peer AVERAGE is an average across peers regardless of the metric's own
    # aggregation (AVG(Premium) / AVG(Score) — the rules/gpr.py / rules/survey.py
    # definition), so the measure column is resolved but the aggregation is AVG.
    column, _ = resolve_measure(spec, args.metric)
    agg = "AVG"
    cuts = _cut_columns(spec, args.group_by)
    params: Dict[str, Any] = {"subject": subject}

    peer_where = [f'LOWER("{peer["key"]}") = LOWER(:subject)']
    country_col = peer.get("country")
    country_val = args.filters.get(spec.entity_columns.get("country"))
    if country_col and country_val:
        params["pcountry"] = country_val
        peer_where.append(f'LOWER("{country_col}") = LOWER(:pcountry)')
    peer_sub = (
        f'SELECT DISTINCT "{peer["members"]}" FROM "{peer["table"]}" '
        f'WHERE {" AND ".join(peer_where)}'
    )

    # All other filters apply to the measure table; the subject carrier filter is
    # excluded (we want the peers, not the subject).
    clauses = [f'"{carrier_col}" IN ({peer_sub})']
    for i, (col, val) in enumerate(
        (k, v) for k, v in args.filters.items() if k != carrier_col
    ):
        c = safe_column(spec, col)
        key = f"f{i}"
        clauses.append(
            f'LOWER("{c}") = LOWER(:{key})' if isinstance(val, str) else f'"{c}" = :{key}'
        )
        params[key] = val

    cut_sel = ", ".join(f'"{c}"' for c in cuts)
    select = (cut_sel + ", " if cut_sel else "") + f'{agg}("{column}") AS value'
    group = f" GROUP BY {cut_sel}" if cut_sel else ""
    sql = (
        f'SELECT {select} FROM "{spec.primary_table}" '
        f'WHERE {" AND ".join(clauses)}{group} ORDER BY value DESC'
    )
    rows = run_rows(eng, sql, params)
    return [
        AnalyticsFact(
            name="peer_average",
            value=round(_num(row["value"]), 2),
            unit=column,
            rendered=f'{_num(row["value"]):,.2f}',
            dims={c: row[c] for c in cuts},
            support=[row],
            formula=f"{agg}({column}) over the subject's peer set",
        )
        for row in rows
    ]


def compute_share_of_wallet(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """Share of Wallet: the carrier's premium as a % of the TOTAL market premium
    for each slice (carrier / all-carriers-in-slice) — the recipe in rules/gpr.py."""
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, _ = resolve_measure(spec, args.metric or "premium")
    carrier = spec.entity_columns.get("carrier")
    subject = args.subject or args.filters.get(carrier)
    if not subject:
        return []
    cuts = _cut_columns(spec, args.group_by)
    # Denominator spans all carriers, so the subject carrier filter is excluded.
    filters = {k: v for k, v in args.filters.items() if k != carrier}
    params: Dict[str, Any] = {}
    where = where_clause(spec, filters, params)
    params["subject"] = subject
    cut_sel = ", ".join(f'"{c}"' for c in cuts)
    group_cols = ", ".join([f'"{carrier}"'] + [f'"{c}"' for c in cuts])
    partition = f"PARTITION BY {cut_sel}" if cut_sel else ""
    sql = f"""
        WITH totals AS (
            SELECT "{carrier}" AS carrier{", " + cut_sel if cut_sel else ""},
                   SUM("{column}") AS carrier_premium,
                   SUM(SUM("{column}")) OVER ({partition}) AS total_premium
            FROM "{spec.primary_table}"{where}
            GROUP BY {group_cols}
        )
        SELECT *, ROUND(100.0 * carrier_premium / NULLIF(total_premium, 0), 1) AS sow
        FROM totals
        WHERE LOWER(carrier) = LOWER(:subject)
        ORDER BY sow DESC
    """
    rows = run_rows(eng, sql, params)
    return [
        AnalyticsFact(
            name="share_of_wallet",
            value=_num(row["sow"]),
            unit="%",
            rendered=f'{_num(row["sow"]):.1f}%',
            dims={"carrier": row["carrier"], **{c: row[c] for c in cuts}},
            support=[row],
            formula="carrier premium / total market premium per slice * 100",
        )
        for row in rows
    ]


def compute_nps(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """Net Promoter Score per cut: %promoters (>=9) - %detractors (<=6), as a
    business-readable -100..100 number, not a raw average."""
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, _ = resolve_measure(spec, "nps")
    cuts = _cut_columns(spec, args.group_by)
    params: Dict[str, Any] = {}
    where = where_clause(spec, args.filters, params)
    cut_sel = ", ".join(f'"{c}"' for c in cuts)
    nps_expr = (
        f'ROUND(100.0 * (SUM(CASE WHEN "{column}" >= 9 THEN 1 ELSE 0 END) '
        f'- SUM(CASE WHEN "{column}" <= 6 THEN 1 ELSE 0 END)) '
        f'/ NULLIF(COUNT("{column}"), 0), 1) AS nps'
    )
    select = (cut_sel + ", " if cut_sel else "") + nps_expr
    group = f" GROUP BY {cut_sel}" if cut_sel else ""
    sql = f'SELECT {select} FROM "{spec.primary_table}"{where}{group} ORDER BY nps DESC'
    rows = run_rows(eng, sql, params)
    return [
        AnalyticsFact(
            name="nps",
            value=_num(row["nps"]),
            unit="NPS",
            rendered=f'{_num(row["nps"]):+.1f}',
            dims={c: row[c] for c in cuts},
            support=[row],
            formula="(%promoters>=9 - %detractors<=6) * 100",
        )
        for row in rows
    ]


def compute_attribute_breakdown(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """Survey AVG(Score) per Section/Attribute cut — the perception-domain
    breakdown. A thin specialization of `compute_breakdown` (metric defaults to
    score), rebranded so the composite that consumes it reads clearly."""
    facts = compute_breakdown(replace(args, metric=args.metric or "score"), engine=engine)
    return [
        replace(
            fact,
            name="attribute_breakdown",
            formula=f'AVG(Score) by {", ".join(args.group_by) or "all"}',
        )
        for fact in facts
    ]


# ── Tier 2 — composite ─────────────────────────────────────────────────────

def find_whitespace(
    args: PrimitiveArgs,
    *,
    engine: Optional[Any] = None,
    top_n: int = 3,
    near_zero: float = 0.0,
    material: float = 0.0,
) -> List[AnalyticsFact]:
    """Whitespace: cuts where the carrier's premium is ~0 but the market is
    materially present. Composes `compute_breakdown` (carrier premium, carrier
    filter retained) and `compute_market_presence` (market premium, carrier
    excluded); owns ONLY the gap rule — no premium/market math of its own.
    """
    eng = resolve_engine(engine)
    premium_args = replace(args, metric="premium")
    carrier_premium = {
        fact.dims_key: fact.value
        for fact in compute_breakdown(premium_args, engine=eng)
    }
    market = compute_market_presence(premium_args, engine=eng)

    gaps = [
        AnalyticsFact(
            name="whitespace",
            value=fact.value,
            unit=fact.unit,
            rendered=fact.rendered,
            dims=dict(fact.dims),
            support=fact.support,
            formula="carrier premium ~0 AND market premium material",
        )
        for fact in market
        if carrier_premium.get(fact.dims_key, 0.0) <= near_zero and fact.value > material
    ]
    gaps.sort(key=lambda f: f.value, reverse=True)
    return gaps[:top_n]


def find_service_gaps(
    args: PrimitiveArgs,
    *,
    engine: Optional[Any] = None,
    top_n: int = 3,
    shortfall: float = 0.5,
) -> List[AnalyticsFact]:
    """Service gaps (survey sibling of whitespace): cuts where the carrier's
    score is materially below its peer average. Composes
    `compute_attribute_breakdown` (carrier score) and `compute_peer_average`
    (peer score); owns ONLY the shortfall rule — no premium/market math.
    """
    eng = resolve_engine(engine)
    score_args = replace(args, metric="score")
    carrier = {
        fact.dims_key: fact.value
        for fact in compute_attribute_breakdown(score_args, engine=eng)
    }
    peer = {fact.dims_key: fact.value for fact in compute_peer_average(score_args, engine=eng)}

    gaps: List[AnalyticsFact] = []
    for key, carrier_score in carrier.items():
        if key not in peer:
            continue
        delta = round(peer[key] - carrier_score, 2)
        if delta >= shortfall:
            gaps.append(
                AnalyticsFact(
                    name="service_gap",
                    value=delta,
                    unit="score",
                    rendered=f"-{delta} vs peer",
                    dims=dict(key),
                    support=[],
                    formula="peer avg score - carrier score >= shortfall",
                )
            )
    gaps.sort(key=lambda f: f.value, reverse=True)
    return gaps[:top_n]


# ── Dispatch ───────────────────────────────────────────────────────────────
# Name → primitive, all callable as ``fn(args, engine=engine)`` (composites carry
# defaulted tuning kwargs). The orchestrator dispatches over this map; the planner
# allowlist is its keys.
LIBRARY: Dict[str, Any] = {
    "compute_breakdown": compute_breakdown,
    "compute_rank": compute_rank,
    "compute_yoy": compute_yoy,
    "compute_share_of_portfolio": compute_share_of_portfolio,
    "compute_market_presence": compute_market_presence,
    "compute_peer_average": compute_peer_average,
    "compute_share_of_wallet": compute_share_of_wallet,
    "compute_nps": compute_nps,
    "compute_attribute_breakdown": compute_attribute_breakdown,
    "find_whitespace": find_whitespace,
    "find_service_gaps": find_service_gaps,
}
