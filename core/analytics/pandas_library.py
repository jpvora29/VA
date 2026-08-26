"""The analytics primitives, computed in pandas over a :class:`FrameSource`.

The twin of :mod:`core.analytics.library`: same arguments, same ``AnalyticsFact``
contract, same recipes — a different executor. ``library`` dispatches here whenever
the "engine" it is handed is a ``FrameSource`` (an uploaded dataset), so a custom
dataset gets the WHOLE library rather than the handful of queries its columns happen
to satisfy.

Only the leaf primitives live here. The composites (``compute_ttm``,
``compute_attribute_breakdown``, ``find_whitespace``, ``find_service_gaps``) are
already written in Python over other primitives and thread the same source through,
so they follow this backend for free.

Two behaviours differ from SQL, and both are the point (see :mod:`core.analytics.frames`):
a cut over an absent column yields no facts; a filter on an absent column matches no
rows. Everything else — case-insensitive text matching, ``RANK()`` semantics, the
NULL group, the ordering — mirrors the SQL exactly, and the parity tests pin it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from core.analytics.frames import FrameSource
from core.analytics.sql import flow_spec, resolve_measure, safe_column
from core.analytics.types import AnalyticsFact, PrimitiveArgs
from logger import get_logger

logger = get_logger(__name__)

_BLANK = (None, "", "all", "All")


# ── frame plumbing ───────────────────────────────────────────────────────────


def _num(value: Any) -> float:
    """Coerce a possibly-null aggregate to a float — the SQL helper's twin."""
    try:
        return 0.0 if value is None or pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return 0.0


def _cell(value: Any) -> Any:
    """A grouped key as a plain python value (NaN → None, numpy scalar → scalar)."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def _primary(source: FrameSource, spec) -> pd.DataFrame:
    return source.table(spec.primary_table)


def _has(frame: pd.DataFrame, column: str) -> bool:
    return column in frame.columns


def _cuts(spec, frame: pd.DataFrame, group_by: Sequence[str]) -> Optional[List[str]]:
    """The validated cut columns, or None when the data has no such column.

    Still validated against the registry (``safe_column``) so a hallucinated column is
    an error either way; only ABSENCE from this particular upload is the soft case.
    """
    cuts = [safe_column(spec, c) for c in group_by]
    missing = [c for c in cuts if not _has(frame, c)]
    if missing:
        logger.info("pandas primitives: no cut for absent column(s) %s", ", ".join(missing))
        return None
    return cuts


def _values(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple, set)):
        return [v for v in value if v not in _BLANK]
    return [value]


def _mask_for(frame: pd.DataFrame, column: str, value: Any) -> pd.Series:
    """One filter's row mask — text compared case-insensitively, as the SQL does."""
    wanted = _values(value)
    if not wanted:
        return pd.Series(True, index=frame.index)
    series = frame[column]
    if all(isinstance(v, str) for v in wanted):
        needles = {v.strip().lower() for v in wanted}
        return series.astype(str).str.strip().str.lower().isin(needles)
    # Mixed/numeric: compare on the string form so 2025 matches "2025" from a text column.
    numeric = pd.to_numeric(series, errors="coerce")
    as_numbers = {float(v) for v in wanted if isinstance(v, (int, float)) and not isinstance(v, bool)}
    mask = numeric.isin(as_numbers) if as_numbers else pd.Series(False, index=frame.index)
    return mask | series.astype(str).isin({str(v) for v in wanted})


def _apply_filters(spec, frame: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    """``frame`` narrowed by ``filters`` — the pandas twin of ``where_clause``."""
    out = frame
    for column, value in (filters or {}).items():
        col = safe_column(spec, column)
        if not _has(out, col):
            # An AND constraint that cannot be evaluated cannot be satisfied.
            logger.info("pandas primitives: filter on absent column %r matches nothing", col)
            return out.iloc[0:0]
        out = out[_mask_for(out, col, value)]
    return out


_AGGREGATIONS = {"SUM": "sum", "AVG": "mean", "COUNT": "count", "MIN": "min", "MAX": "max"}


def _measure(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def _aggregate(frame: pd.DataFrame, column: str, agg: str,
               cuts: Sequence[str]) -> List[Tuple[Dict[str, Any], float]]:
    """``[(cut dims, value)]`` — the shared aggregation core, biggest value first.

    ``dropna=False`` keeps the NULL group SQL's ``GROUP BY`` would produce.
    """
    how = _AGGREGATIONS.get(agg.upper(), "sum")
    values = _measure(frame, column)
    if not cuts:
        total = getattr(values, how)()
        return [({}, _num(total))]
    grouped = values.groupby([frame[c] for c in cuts], dropna=False)
    rows = [
        ({c: _cell(k) for c, k in zip(cuts, key if isinstance(key, tuple) else (key,))}, _num(val))
        for key, val in getattr(grouped, how)().items()
    ]
    rows.sort(key=lambda row: row[1], reverse=True)
    return rows


def _prepared(args: PrimitiveArgs, source: FrameSource, *, metric: str = "",
              drop: Sequence[str] = ()) -> Tuple[Any, Optional[pd.DataFrame], str, str]:
    """``(spec, filtered frame, measure column, aggregation)`` for one call.

    The frame is ``None`` when this source cannot answer the question AT ALL — no such
    table, or no such measure in it (an uploaded premium book has no survey ``Score``).
    That is different from "no rows matched", which is a real zero: a primitive that
    cannot be computed must yield NO fact, or the deck would show a fabricated 0.0
    where it should show the template's own placeholder.
    """
    spec = flow_spec(args.flow)
    column, agg = resolve_measure(spec, metric or args.metric)
    frame = _primary(source, spec)
    if frame.empty and not source.has(spec.primary_table):
        logger.info("pandas primitives: source has no table %r", spec.primary_table)
        return spec, None, column, agg
    if not _has(frame, column):
        logger.info("pandas primitives: no measure column %r in %r", column, spec.primary_table)
        return spec, None, column, agg
    filters = {k: v for k, v in args.filters.items() if k not in set(drop)}
    return spec, _apply_filters(spec, frame, filters), column, agg


def _fact(name: str, value: float, unit: str, rendered: str,
          dims: Dict[str, Any], formula: str, support: Dict[str, Any]) -> AnalyticsFact:
    return AnalyticsFact(name=name, value=value, unit=unit, rendered=rendered,
                         dims=dims, support=[support], formula=formula)


# ── Tier 1 — atomic, shared ──────────────────────────────────────────────────


def compute_breakdown(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """The measure per group_by cut, under the given filters."""
    spec, frame, column, agg = _prepared(args, source)
    cuts = _cuts(spec, _primary(source, spec), args.group_by)
    if frame is None or cuts is None:
        return []
    if frame.empty:
        return _empty_breakdown(column, agg, cuts)
    return [
        _fact("breakdown", value, column, f"{value:,.1f}", dims,
              f'{agg}({column}) by {", ".join(cuts) or "all"}', {**dims, "value": value})
        for dims, value in _aggregate(frame, column, agg, cuts)
    ]


def _empty_breakdown(column: str, agg: str, cuts: Sequence[str]) -> List[AnalyticsFact]:
    """No rows in scope. An ungrouped total is still a number (zero); a cut is nothing."""
    if cuts:
        return []
    return [_fact("breakdown", 0.0, column, "0.0", {},
                  f"{agg}({column}) by all", {"value": 0.0})]


def compute_rank(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """Rank entities (carriers) by the measure, within each group_by cut."""
    spec, frame, column, agg = _prepared(args, source)
    entity = spec.entity_columns.get("carrier")
    cuts = _cuts(spec, _primary(source, spec), args.group_by)
    if frame is None or cuts is None or not entity or frame.empty or not _has(frame, entity):
        return []
    totals = _aggregate(frame, column, agg, [entity, *cuts])
    facts: List[AnalyticsFact] = []
    # Cut, then rank within it — the order the SQL's ``ORDER BY cut, rank`` produces.
    for cut_key, group in sorted(_by_cut(totals, entity, cuts).items(), key=_cut_order):
        ordered = sorted(group, key=lambda row: row[1], reverse=True)
        of_n = len(ordered)
        for position, (dims, value) in enumerate(ordered, start=1):
            rank = _tied_rank(ordered, position, value)
            facts.append(
                _fact("rank", rank, "rank", f"#{rank} of {of_n}",
                      {"entity": dims[entity], **dict(cut_key)},
                      f"RANK() over {agg}({column}) desc",
                      {"entity": dims[entity], "measure": value, "rank": rank, "of_n": of_n})
            )
    return facts


def _by_cut(totals, entity: str, cuts: Sequence[str]) -> Dict[Tuple, List]:
    """Group ``(dims, value)`` rows by their non-entity cut — the RANK() partition."""
    out: Dict[Tuple, List] = {}
    for dims, value in totals:
        key = tuple((c, dims[c]) for c in cuts)
        out.setdefault(key, []).append((dims, value))
    return out


def _cut_order(item: Tuple[Tuple, List]) -> Tuple:
    """Sort key for a cut partition — its values, ordered as SQLite orders them."""
    return tuple(_sortable(value) for _column, value in item[0])


def _tied_rank(ordered: Sequence[Tuple[Dict[str, Any], float]], position: int, value: float) -> int:
    """SQL ``RANK()``: ties share the first position of their run, then it gaps."""
    first = next(i for i, (_, v) in enumerate(ordered, start=1) if v == value)
    return first if first < position else position


def compute_yoy(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """Year-over-year % change of the measure, per group_by cut."""
    spec, frame, column, agg = _prepared(args, source)
    year = spec.date_columns.get("year")
    cuts = _cuts(spec, _primary(source, spec), args.group_by)
    if frame is None or cuts is None or not year or frame.empty or not _has(frame, year):
        return []
    totals = _aggregate(frame, column, agg, [year, *cuts])
    facts: List[AnalyticsFact] = []
    for cut_key, group in _by_cut(totals, year, cuts).items():
        series = sorted(((row[year], value) for row, value in group),
                        key=lambda pair: _sortable(pair[0]))
        for (_, prior), (current_year, current) in zip(series, series[1:]):
            if not prior:
                continue
            pct = round((current - prior) / prior * 100, 1)
            facts.append(
                _fact("yoy", pct, "%", f"{pct:+.1f}%",
                      {"year": current_year, **dict(cut_key)},
                      "(current - prior) / prior * 100, by year",
                      {"yr": current_year, "measure": current, "prev": prior})
            )
    # Chronological across every cut, then by cut — the order the SQL's ``ORDER BY yr``
    # over a grouped CTE emits (a GROUP BY comes out in key order).
    facts.sort(key=lambda fact: (_sortable(fact.dims["year"]), _dims_order(fact, cuts)))
    return facts


def _dims_order(fact: AnalyticsFact, cuts: Sequence[str]) -> Tuple:
    """Sort key over a fact's cut values — the tiebreak that keeps output stable."""
    return tuple(_sortable(fact.dims.get(c)) for c in cuts)


def _sortable(value: Any) -> Tuple[int, Any]:
    """Order keys with None last, numbers before strings — SQLite's ORDER BY shape."""
    if value is None:
        return (2, 0)
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


# ── Tier 1 — atomic, GPR premium domain ──────────────────────────────────────


def compute_share_of_portfolio(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """Each cut's premium as a % of the carrier's OWN book."""
    spec, frame, column, _agg = _prepared(args, source, metric=args.metric or "premium")
    carrier = spec.entity_columns.get("carrier")
    cuts = _cuts(spec, _primary(source, spec), args.group_by)
    if frame is None or cuts is None or not carrier or frame.empty or not _has(frame, carrier):
        return []
    totals = _aggregate(frame, column, "SUM", [carrier, *cuts])
    book: Dict[Any, float] = {}
    for dims, value in totals:
        book[dims[carrier]] = book.get(dims[carrier], 0.0) + value
    facts = []
    for dims, value in totals:
        whole = book.get(dims[carrier]) or 0.0
        pct = round(100.0 * value / whole, 1) if whole else 0.0
        facts.append(
            _fact("share_of_portfolio", pct, "%", f"{pct:.1f}%",
                  {"carrier": dims[carrier], **{c: dims[c] for c in cuts}},
                  "SUM(Premium) per cut / carrier total Premium * 100",
                  {"carrier": dims[carrier], "carrier_premium": value, "sop_pct": pct})
        )
    facts.sort(key=lambda f: (-f.value, _dims_order(f, cuts)))
    return facts


def compute_market_presence(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """Total premium per cut with the CARRIER filter dropped — the market context."""
    spec = flow_spec(args.flow)
    carrier = spec.entity_columns.get("carrier")
    _spec, frame, column, agg = _prepared(args, source, metric=args.metric or "premium",
                                          drop=(carrier,) if carrier else ())
    cuts = _cuts(spec, _primary(source, spec), args.group_by)
    if frame is None or cuts is None or frame.empty:
        return []
    return [
        _fact("market_presence", value, column, f"{value:,.1f}", dims,
              f"{agg}({column}) per cut, carrier filter excluded", {**dims, "value": value})
        for dims, value in _aggregate(frame, column, agg, cuts)
    ]


def compute_share_of_wallet(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """The subject's premium as a % of the TOTAL market premium for each slice."""
    spec = flow_spec(args.flow)
    carrier = spec.entity_columns.get("carrier")
    subject = args.subject or args.filters.get(carrier)
    if not subject or not carrier:
        return []
    _spec, frame, column, _agg = _prepared(args, source, metric=args.metric or "premium",
                                           drop=(carrier,))
    cuts = _cuts(spec, _primary(source, spec), args.group_by)
    if frame is None or cuts is None or frame.empty or not _has(frame, carrier):
        return []
    totals = _aggregate(frame, column, "SUM", [carrier, *cuts])
    market: Dict[Tuple, float] = {}
    for dims, value in totals:
        key = tuple((c, dims[c]) for c in cuts)
        market[key] = market.get(key, 0.0) + value

    facts = []
    for dims, value in totals:
        if str(dims[carrier]).strip().lower() != str(subject).strip().lower():
            continue
        key = tuple((c, dims[c]) for c in cuts)
        whole = market.get(key) or 0.0
        sow = round(100.0 * value / whole, 1) if whole else 0.0
        facts.append(
            _fact("share_of_wallet", sow, "%", f"{sow:.1f}%",
                  {"carrier": dims[carrier], **{c: dims[c] for c in cuts}},
                  "carrier premium / total market premium per slice * 100",
                  {"carrier": dims[carrier], "carrier_premium": value,
                   "total_premium": whole, "sow": sow})
        )
    facts.sort(key=lambda f: (-f.value, _dims_order(f, cuts)))
    return facts


def compute_nps(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """%promoters (>=9) − %detractors (<=6) per cut, as a -100..100 number."""
    spec = flow_spec(args.flow)
    column, _ = resolve_measure(spec, "nps")
    frame = _primary(source, spec)
    cuts = _cuts(spec, frame, args.group_by)
    if cuts is None or not _has(frame, column):
        return []
    frame = _apply_filters(spec, frame, args.filters)
    if frame.empty:
        return []
    scores = _measure(frame, column)
    groups = ([(tuple(), frame.index)] if not cuts else
              list(frame.groupby([frame[c] for c in cuts], dropna=False).groups.items()))
    facts = []
    for key, index in groups:
        block = scores.loc[index].dropna()
        answered = len(block)
        if not answered:
            continue
        nps = round(100.0 * ((block >= 9).sum() - (block <= 6).sum()) / answered, 1)
        keys = key if isinstance(key, tuple) else (key,)
        dims = {c: _cell(k) for c, k in zip(cuts, keys)}
        facts.append(_fact("nps", nps, "NPS", f"{nps:+.1f}", dims,
                           "(%promoters>=9 - %detractors<=6) * 100", {**dims, "nps": nps}))
    facts.sort(key=lambda f: f.value, reverse=True)
    return facts


# ── peers ────────────────────────────────────────────────────────────────────


def _peer_frame(source: FrameSource, spec, args: PrimitiveArgs) -> Optional[pd.DataFrame]:
    """The subject's peer rows in the primary table, or None when peers can't resolve.

    Mirrors ``library._peer_clauses``: a pinned custom set wins; otherwise membership
    comes from the Peers table, scoped to the selected country when both the flow and
    the actual table carry one. The subject's own carrier filter is always dropped.
    """
    peer = spec.peer_columns or {}
    carrier = spec.entity_columns.get("carrier")
    subject = args.subject or args.filters.get(carrier)
    if not peer or not carrier or not subject:
        return None
    frame = _primary(source, spec)
    if not _has(frame, carrier):
        return None
    members = _pinned(args) or _peer_members(source, spec, args, subject)
    if not members:
        return None
    scoped = _apply_filters(spec, frame, {k: v for k, v in args.filters.items() if k != carrier})
    return scoped[scoped[carrier].astype(str).str.strip().str.lower().isin(members)]


def _pinned(args: PrimitiveArgs) -> set:
    return {str(p).strip().lower() for p in (args.peers or []) if str(p).strip()}


def _peer_members(source: FrameSource, spec, args: PrimitiveArgs, subject: Any) -> set:
    """The subject's peer group from the Peers table (country-scoped when possible)."""
    peer = spec.peer_columns
    table = source.table(peer.get("table", ""))
    key, members = peer.get("key"), peer.get("members")
    if table.empty or key not in table.columns or members not in table.columns:
        return set()
    rows = table[table[key].astype(str).str.strip().str.lower() == str(subject).strip().lower()]
    country_col = peer.get("country")
    country_val = args.filters.get(spec.entity_columns.get("country"))
    if country_col and country_col in table.columns and country_val:
        wanted = {str(v).strip().lower() for v in _values(country_val)}
        if wanted:
            rows = rows[rows[country_col].astype(str).str.strip().str.lower().isin(wanted)]
    return {str(v).strip().lower() for v in rows[members].dropna().unique()}


def compute_peer_average(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """The peer group's per-ROW average of the measure, per cut (scores, not premium)."""
    spec = flow_spec(args.flow)
    column, _ = resolve_measure(spec, args.metric)
    frame = _peer_frame(source, spec, args)
    cuts = _cuts(spec, _primary(source, spec), args.group_by)
    if frame is None or cuts is None or frame.empty or not _has(frame, column):
        return []
    return [
        _fact("peer_average", round(value, 2), column, f"{value:,.2f}", dims,
              f"AVG({column}) over the subject's peer set", {**dims, "value": value})
        for dims, value in _aggregate(frame, column, "AVG", cuts)
    ]


def compute_peer_average_total(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """Average of each peer's TOTAL measure — the right benchmark for premium.

    Confidential: one aggregate fact whose ``dims`` carry the peer COUNT, never a name.
    """
    spec = flow_spec(args.flow)
    column, agg = resolve_measure(spec, args.metric)
    carrier = spec.entity_columns.get("carrier")
    frame = _peer_frame(source, spec, args)
    if frame is None or frame.empty or not _has(frame, column):
        return []
    per_peer = _aggregate(frame, column, agg, [carrier])
    if not per_peer:
        return []
    value = round(sum(v for _, v in per_peer) / len(per_peer), 2)
    return [
        _fact("peer_average_total", value, column, f"{value:,.2f}",
              {"peers": len(per_peer)},
              f"AVG over peers of {agg}({column}) — average of peer totals",
              {"value": value, "n": len(per_peer)})
    ]


# ── Tier 1 — atomic, temporal ────────────────────────────────────────────────


def _periods(frame: pd.DataFrame, date_column: str, grain: str) -> pd.Series:
    """The date column bucketed into ``YYYY-MM`` or ``YYYY-Qn`` labels."""
    stamps = pd.to_datetime(frame[date_column], errors="coerce")
    if grain == "month":
        return stamps.dt.strftime("%Y-%m")
    if grain == "quarter":
        return stamps.dt.year.astype("Int64").astype(str) + "-Q" + stamps.dt.quarter.astype("Int64").astype(str)
    raise ValueError(f"unknown period grain {grain!r}")


def _period_totals(source: FrameSource, args: PrimitiveArgs,
                   grain: str) -> List[Tuple[str, float]]:
    """``[(period label, value)]`` in chronological order — the shared time axis."""
    spec, frame, column, agg = _prepared(args, source)
    date_column = spec.date_columns.get("date")
    if frame is None or not date_column or frame.empty or not _has(frame, date_column):
        return []
    labelled = frame.assign(_period=_periods(frame, date_column, grain))
    labelled = labelled[labelled["_period"].notna() & (labelled["_period"] != "<NA>-Q<NA>")]
    if labelled.empty:
        return []
    rows = _aggregate(labelled, column, agg, ["_period"])
    return sorted(((str(dims["_period"]), value) for dims, value in rows), key=lambda r: r[0])


def compute_period_series(source: FrameSource, args: PrimitiveArgs,
                          *, grain: str = "month") -> List[AnalyticsFact]:
    """The measure per calendar period (month or quarter), chronologically."""
    spec = flow_spec(args.flow)
    column, agg = resolve_measure(spec, args.metric)
    return [
        _fact("period_series", value, column, f"{value:,.1f}",
              {"period": period, "grain": grain}, f"{agg}({column}) by {grain}",
              {"period": period, "value": value})
        for period, value in _period_totals(source, args, grain)
    ]


def compute_period_change(source: FrameSource, args: PrimitiveArgs,
                          *, grain: str = "month") -> List[AnalyticsFact]:
    """Period-over-period % change (month ⇒ MoM, quarter ⇒ QoQ)."""
    series = _period_totals(source, args, grain)
    facts = []
    for (_, prior), (period, current) in zip(series, series[1:]):
        if not prior:
            continue
        pct = round((current - prior) / prior * 100, 1)
        facts.append(
            _fact("period_change", pct, "%", f"{pct:+.1f}%",
                  {"period": period, "grain": grain},
                  f"(current - prior) / prior * 100, by {grain}",
                  {"period": period, "measure": current, "prev": prior})
        )
    return facts


# ── How far the data reaches, and like-for-like YoY ──────────────────────────
#
# The pandas twins of `library.get_latest_year` / `get_latest_quarter` /
# `compute_yoy_to_date`. Same contract, same facts: an uploaded book that stops in
# May must not read as a collapse against a full prior year.

_PERIODS_PER_YEAR = {"quarter": 4, "month": 12}


def _period_filter_columns(spec) -> List[str]:
    """The flow's date-ish columns — the filters a "latest period" question drops."""
    return [str(name) for name in spec.date_columns.values() if name]


def _year_series(frame: pd.DataFrame, spec) -> Optional[pd.Series]:
    """The calendar year per row — declared year column, else read off the date."""
    year = spec.date_columns.get("year")
    if year and _has(frame, year):
        return pd.to_numeric(frame[year], errors="coerce").astype("Int64")
    date_column = spec.date_columns.get("date")
    if date_column and _has(frame, date_column):
        return pd.to_datetime(frame[date_column], errors="coerce").dt.year.astype("Int64")
    return None


def _position_series(frame: pd.DataFrame, spec, grain: str) -> Optional[pd.Series]:
    """The period's position within its year: 1-4 quarterly, 1-12 monthly."""
    quarter = spec.date_columns.get("quarter")
    date_column = spec.date_columns.get("date")
    if grain == "quarter" and quarter and _has(frame, quarter):
        cleaned = frame[quarter].astype(str).str.replace(r"(?i)q", "", regex=True)
        return pd.to_numeric(cleaned, errors="coerce").astype("Int64")
    if not (date_column and _has(frame, date_column)):
        return None
    stamps = pd.to_datetime(frame[date_column], errors="coerce")
    if grain == "quarter":
        return stamps.dt.quarter.astype("Int64")
    if grain == "month":
        return stamps.dt.month.astype("Int64")
    raise ValueError(f"unknown period grain {grain!r}")


def _period_label(grain: str, position: Any) -> str:
    """``2`` → "Q2" (quarterly) or "M02" (monthly)."""
    try:
        number = int(position)
    except (TypeError, ValueError):
        return ""
    return f"Q{number}" if grain == "quarter" else f"M{number:02d}"


def get_latest_year(source: FrameSource, args: PrimitiveArgs) -> List[AnalyticsFact]:
    """The most recent year the data reaches for this scope."""
    spec = flow_spec(args.flow)
    _spec, frame, _column, _agg = _prepared(
        args, source, drop=_period_filter_columns(spec)
    )
    if frame is None or frame.empty:
        return []
    years = _year_series(frame, spec)
    if years is None or years.dropna().empty:
        return []
    year = int(years.max())
    return [
        _fact("latest_year", float(year), "year", str(year), {"year": year},
              f"MAX({spec.date_columns.get('year') or 'year(date)'})", {"year": year})
    ]


def get_latest_quarter(source: FrameSource, args: PrimitiveArgs,
                       *, grain: str = "quarter") -> List[AnalyticsFact]:
    """The most recent quarter (or month) reached, and whether its year is complete."""
    spec = flow_spec(args.flow)
    _spec, frame, _column, _agg = _prepared(
        args, source, drop=_period_filter_columns(spec)
    )
    if frame is None or frame.empty:
        return []
    years, positions = _year_series(frame, spec), _position_series(frame, spec, grain)
    if years is None or positions is None or years.dropna().empty:
        return []
    year = int(years.max())
    in_latest = positions[years == year].dropna()
    if in_latest.empty:
        return []
    position = int(in_latest.max())
    label = _period_label(grain, position)
    return [
        _fact(f"latest_{grain}", float(position), grain, f"{label} {year}",
              {"year": year, grain: position, "period": f"{year}-{label}",
               "complete": position >= _PERIODS_PER_YEAR[grain],
               "periods_present": int(in_latest.nunique())},
              f"MAX({grain} of the latest year)",
              {"yr": year, "pin_max": position})
    ]


def compute_yoy_to_date(source: FrameSource, args: PrimitiveArgs,
                        *, grain: str = "quarter") -> List[AnalyticsFact]:
    """Like-for-like YoY: every year truncated to the span the newest year reaches."""
    spec = flow_spec(args.flow)
    _spec, frame, column, agg = _prepared(
        args, source, drop=_period_filter_columns(spec)
    )
    cuts = _cuts(spec, _primary(source, spec), args.group_by)
    if frame is None or cuts is None or frame.empty:
        return []
    years, positions = _year_series(frame, spec), _position_series(frame, spec, grain)
    if years is None or positions is None or years.dropna().empty:
        return []
    latest = int(years.max())
    in_latest = positions[years == latest].dropna()
    if in_latest.empty:
        return []
    cutoff = int(in_latest.max())
    through = _period_label(grain, cutoff)

    aligned = frame[positions.notna() & (positions <= cutoff)]
    if aligned.empty:
        return []
    year_column = "_yoy_year"
    aligned = aligned.assign(**{year_column: years[aligned.index]})
    totals = _aggregate(aligned, column, agg, [year_column, *cuts])

    facts: List[AnalyticsFact] = []
    for cut_key, group in _by_cut(totals, year_column, cuts).items():
        series = sorted(((row[year_column], value) for row, value in group),
                        key=lambda pair: _sortable(pair[0]))
        for (_, prior), (current_year, current) in zip(series, series[1:]):
            if not prior:
                continue
            pct = round((current - prior) / prior * 100, 1)
            facts.append(
                _fact("yoy_to_date", pct, "%", f"{pct:+.1f}%",
                      {"year": current_year, "through": through, "grain": grain,
                       **dict(cut_key)},
                      f"(current - prior) / prior * 100, by year, "
                      f"both truncated to {through or grain}",
                      {"yr": current_year, "measure": current, "prev": prior,
                       "pin_max": cutoff})
            )
    facts.sort(key=lambda fact: (_sortable(fact.dims["year"]), _dims_order(fact, cuts)))
    return facts


# ── Dispatch ─────────────────────────────────────────────────────────────────
# Primitive name → its pandas implementation. ``library`` reads this map to decide
# what it can route; a name absent here simply stays on SQL.
PANDAS_LIBRARY: Dict[str, Any] = {
    "compute_breakdown": compute_breakdown,
    "compute_rank": compute_rank,
    "compute_yoy": compute_yoy,
    "compute_yoy_to_date": compute_yoy_to_date,
    "get_latest_year": get_latest_year,
    "get_latest_quarter": get_latest_quarter,
    "compute_share_of_portfolio": compute_share_of_portfolio,
    "compute_market_presence": compute_market_presence,
    "compute_share_of_wallet": compute_share_of_wallet,
    "compute_peer_average": compute_peer_average,
    "compute_peer_average_total": compute_peer_average_total,
    "compute_nps": compute_nps,
    "compute_period_series": compute_period_series,
    "compute_period_change": compute_period_change,
}
