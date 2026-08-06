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

**Two executors, one contract.** When the injected "engine" is a
:class:`~core.analytics.frames.FrameSource` — an uploaded dataset, whose tables are
DataFrames and whose columns are whatever the user's spreadsheet had — the call is
routed to its pandas twin in :mod:`core.analytics.pandas_library` (`@_on_frames`).
Same arguments, same facts, no SQL. The composites need no routing of their own:
they are Python over other primitives and thread the same source down.
"""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.analytics import pandas_library as P
from core.analytics.frames import as_frame_source
from core.analytics.sql import (
    flow_spec,
    peer_country_column,
    resolve_engine,
    resolve_measure,
    run_rows,
    safe_column,
    where_clause,
)
from core.analytics.types import AnalyticsFact, PrimitiveArgs


def _on_frames(pandas_fn: Callable) -> Callable:
    """Route a primitive to ``pandas_fn`` when its engine is a ``FrameSource``.

    The whole two-executor seam, in one decorator: the SQL body below each of these
    is untouched and still runs for every real engine. Tuning kwargs (``grain``,
    ``top_n``…) pass through unchanged, so both executors take the same call.
    """
    def decorate(sql_fn: Callable) -> Callable:
        @wraps(sql_fn)
        def run(args: PrimitiveArgs, *, engine: Optional[Any] = None, **kwargs):
            source = as_frame_source(engine)
            if source is not None:
                return pandas_fn(source, args, **kwargs)
            return sql_fn(args, engine=engine, **kwargs)

        run.on_sql = sql_fn                     # the SQL body, for parity tests
        return run
    return decorate


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

@_on_frames(P.compute_breakdown)
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


@_on_frames(P.compute_rank)
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


@_on_frames(P.compute_yoy)
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

@_on_frames(P.compute_share_of_portfolio)
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


@_on_frames(P.compute_market_presence)
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


def _peer_clauses(
    spec, args: PrimitiveArgs, params: Dict[str, Any], engine: Optional[Any] = None
) -> Optional[Tuple[str, List[str]]]:
    """Build the SQL clauses selecting the subject's peer set under the args' filters.

    Returns ``(carrier_col, [where clauses])`` or None when the flow has no peer
    config / no subject. Shared by the per-row peer average and the per-peer-total
    peer average so both resolve the SAME peer membership the same way. A pinned
    custom peer set overrides the Peers-table lookup; the subject's own carrier
    filter is always excluded (we want the peers, not the subject).

    When the flow declares a peer country column AND the Peers table really has
    one, the group is scoped to the selected country so the benchmark is
    like-for-like in that market.
    """
    peer = spec.peer_columns
    carrier_col = spec.entity_columns.get("carrier")
    subject = args.subject or args.filters.get(carrier_col)
    if not peer or not carrier_col or not subject:
        return None

    params["subject"] = subject
    pinned = [str(p).strip() for p in (args.peers or []) if str(p).strip()]
    if pinned:
        ph = []
        for j, p in enumerate(pinned):
            k = f"cp{j}"
            params[k] = p
            ph.append(f"LOWER(:{k})")
        member_clause = f'LOWER("{carrier_col}") IN ({", ".join(ph)})'
    else:
        peer_where = [f'LOWER("{peer["key"]}") = LOWER(:subject)']
        country_col = peer_country_column(spec, engine) if engine is not None else peer.get("country")
        country_val = args.filters.get(spec.entity_columns.get("country"))
        if country_col and country_val:
            # Honour a multi-select country filter (IN) as well as a single value.
            cvals = list(country_val) if isinstance(country_val, (list, tuple, set)) else [country_val]
            cvals = [v for v in cvals if v not in (None, "", "all", "All")]
            if cvals:
                cph = []
                for j, v in enumerate(cvals):
                    k = f"pc{j}"
                    params[k] = v
                    cph.append(f"LOWER(:{k})")
                peer_where.append(f'LOWER("{country_col}") IN ({", ".join(cph)})')
        peer_sub = (
            f'SELECT DISTINCT "{peer["members"]}" FROM "{peer["table"]}" '
            f'WHERE {" AND ".join(peer_where)}'
        )
        member_clause = f'"{carrier_col}" IN ({peer_sub})'

    non_carrier = {k: v for k, v in args.filters.items() if k != carrier_col}
    extra = where_clause(spec, non_carrier, params)  # " WHERE …" or ""
    clauses = [member_clause]
    if extra:
        clauses.append(extra.replace(" WHERE ", "", 1))
    return carrier_col, clauses


@_on_frames(P.compute_peer_average)
def compute_peer_average(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """The peer group's per-ROW average of the measure, per group_by cut.

    AVG over the peer set's rows — the right shape for an averaged-by-row metric
    like a survey score (used by `find_service_gaps`). For an additive measure like
    premium, prefer `compute_peer_average_total` (a peer's contribution is its
    total, not its per-row average). Peer AVERAGE only, never individual peers.
    """
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    # Aggregation is AVG regardless of the metric's own (the rules/gpr.py /
    # rules/survey.py definition resolves the measure column, averages across rows).
    column, _ = resolve_measure(spec, args.metric)
    agg = "AVG"
    cuts = _cut_columns(spec, args.group_by)
    params: Dict[str, Any] = {}
    parts = _peer_clauses(spec, args, params, eng)
    if parts is None:
        return []
    _carrier_col, clauses = parts

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


@_on_frames(P.compute_peer_average_total)
def compute_peer_average_total(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """Average of each peer's TOTAL measure: SUM per peer carrier, then AVG across peers.

    The correct 'aggregate peer average' for additive measures like premium — a
    peer's contribution is its total in scope, so the subject's total compares
    like-for-like. (Contrast `compute_peer_average`, which averages per row and is
    only meaningful for averaged metrics like scores.) Confidential: returns a single
    aggregate fact; `dims['peers']` carries only the peer COUNT, never a name.
    """
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric)  # SUM for premium
    params: Dict[str, Any] = {}
    parts = _peer_clauses(spec, args, params, eng)
    if parts is None:
        return []
    carrier_col, clauses = parts

    sql = (
        f'SELECT AVG(carrier_total) AS value, COUNT(*) AS n FROM ('
        f'  SELECT {agg}("{column}") AS carrier_total FROM "{spec.primary_table}" '
        f'  WHERE {" AND ".join(clauses)} GROUP BY "{carrier_col}"'
        f")"
    )
    rows = run_rows(eng, sql, params)
    if not rows or rows[0].get("value") is None:
        return []
    row = rows[0]
    value = _num(row["value"])
    return [
        AnalyticsFact(
            name="peer_average_total",
            value=round(value, 2),
            unit=column,
            rendered=f"{value:,.2f}",
            dims={"peers": int(row.get("n") or 0)},
            support=[row],
            formula=f"AVG over peers of {agg}({column}) — average of peer totals",
        )
    ]


@_on_frames(P.compute_share_of_wallet)
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


@_on_frames(P.compute_nps)
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


# ── Tier 1 — atomic, temporal (sub-year periods from the date column) ────────


def _period_expr(spec, grain: str) -> Optional[str]:
    """SQLite expression bucketing the flow's date column into a period label.

    ``month`` → ``YYYY-MM``; ``quarter`` → ``YYYY-Qn`` (n from the calendar
    month). Returns None when the flow declares no ``date`` column, so callers
    degrade gracefully (no monthly signal) rather than raise.
    """
    date_col = spec.date_columns.get("date")
    if not date_col:
        return None
    safe = safe_column(spec, date_col)
    if grain == "month":
        return f"strftime('%Y-%m', \"{safe}\")"
    if grain == "quarter":
        return (
            f"strftime('%Y', \"{safe}\") || '-Q' || "
            f"CAST((CAST(strftime('%m', \"{safe}\") AS INTEGER) + 2) / 3 AS INTEGER)"
        )
    raise ValueError(f"unknown period grain {grain!r}")


@_on_frames(P.compute_period_series)
def compute_period_series(
    args: PrimitiveArgs, *, grain: str = "month", engine: Optional[Any] = None
) -> List[AnalyticsFact]:
    """The measure per calendar period (month or quarter), in chronological order.

    The time axis for the TTM / QoQ / MoM views — derived from the flow's date
    column (GPR ``Billing_Date``), so it is real and deterministic, not synthetic.
    """
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric)
    pexpr = _period_expr(spec, grain)
    if pexpr is None:
        return []
    params: Dict[str, Any] = {}
    where = where_clause(spec, args.filters, params)
    sql = (
        f'SELECT {pexpr} AS period, {agg}("{column}") AS value '
        f'FROM "{spec.primary_table}"{where} GROUP BY period ORDER BY period'
    )
    rows = run_rows(eng, sql, params)
    return [
        AnalyticsFact(
            name="period_series",
            value=_num(row["value"]),
            unit=column,
            rendered=f'{_num(row["value"]):,.1f}',
            dims={"period": row["period"], "grain": grain},
            support=[row],
            formula=f"{agg}({column}) by {grain}",
        )
        for row in rows
        if row.get("period")
    ]


@_on_frames(P.compute_period_change)
def compute_period_change(
    args: PrimitiveArgs, *, grain: str = "month", engine: Optional[Any] = None
) -> List[AnalyticsFact]:
    """Period-over-period % change of the measure (``grain='month'`` ⇒ MoM,
    ``grain='quarter'`` ⇒ QoQ). Mirrors ``compute_yoy`` with a calendar bucket
    instead of the year column; emits nothing for the first period (no prior).
    """
    spec = flow_spec(args.flow)
    eng = resolve_engine(engine)
    column, agg = resolve_measure(spec, args.metric)
    pexpr = _period_expr(spec, grain)
    if pexpr is None:
        return []
    params: Dict[str, Any] = {}
    where = where_clause(spec, args.filters, params)
    sql = f"""
        WITH agg AS (
            SELECT {pexpr} AS period, {agg}("{column}") AS measure
            FROM "{spec.primary_table}"{where}
            GROUP BY period
        )
        SELECT *, LAG(measure) OVER (ORDER BY period) AS prev FROM agg ORDER BY period
    """
    rows = run_rows(eng, sql, params)
    facts: List[AnalyticsFact] = []
    for row in rows:
        if not row.get("period"):
            continue
        prev = row.get("prev")
        if prev in (None, 0) or _num(prev) == 0.0:
            continue
        pct = round((_num(row["measure"]) - _num(prev)) / _num(prev) * 100, 1)
        facts.append(
            AnalyticsFact(
                name="period_change",
                value=pct,
                unit="%",
                rendered=f"{pct:+.1f}%",
                dims={"period": row["period"], "grain": grain},
                support=[row],
                formula=f"(current - prior) / prior * 100, by {grain}",
            )
        )
    return facts


def compute_ttm(args: PrimitiveArgs, *, engine: Optional[Any] = None) -> List[AnalyticsFact]:
    """Trailing-twelve-month rolling totals over the monthly series.

    Each fact is the sum of the measure over the 12 months ending at its period;
    the final fact's ``support`` carries the prior-TTM window and the TTM-over-TTM
    %, so a renderer can show both the rolling line and the headline TTM delta.
    """
    series = compute_period_series(args, grain="month", engine=engine)
    if len(series) < 12:
        return []
    periods = [str(f.dims["period"]) for f in series]
    values = [f.value for f in series]
    facts: List[AnalyticsFact] = []
    rolling: List[float] = []
    for i in range(11, len(values)):
        window = sum(values[i - 11 : i + 1])
        rolling.append(window)
        facts.append(
            AnalyticsFact(
                name="ttm",
                value=window,
                unit=args.metric or "premium",
                rendered=f"{window:,.1f}",
                dims={"period": periods[i], "window": "trailing12"},
                support=[],
                formula="rolling 12-month sum",
            )
        )
    if len(rolling) >= 13 and rolling[-13]:
        ttm_pct = round((rolling[-1] - rolling[-13]) / rolling[-13] * 100, 1)
        facts[-1].support.append({"prior_ttm": rolling[-13], "ttm_pct": ttm_pct})
    return facts


# ── Dispatch ───────────────────────────────────────────────────────────────
# Name → primitive, all callable as ``fn(args, engine=engine)`` (composites carry
# defaulted tuning kwargs). The orchestrator dispatches over this map; the planner
# allowlist is its keys.
LIBRARY: Dict[str, Any] = {
    "compute_breakdown": compute_breakdown,
    "compute_rank": compute_rank,
    "compute_yoy": compute_yoy,
    "compute_period_series": compute_period_series,
    "compute_period_change": compute_period_change,
    "compute_ttm": compute_ttm,
    "compute_share_of_portfolio": compute_share_of_portfolio,
    "compute_market_presence": compute_market_presence,
    "compute_peer_average": compute_peer_average,
    "compute_peer_average_total": compute_peer_average_total,
    "compute_share_of_wallet": compute_share_of_wallet,
    "compute_nps": compute_nps,
    "compute_attribute_breakdown": compute_attribute_breakdown,
    "find_whitespace": find_whitespace,
    "find_service_gaps": find_service_gaps,
}
