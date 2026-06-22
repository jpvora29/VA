"""Registry-driven SQL helpers for the analytics primitives.

The primitives push aggregation down to SQLite; this module owns the safe,
parametrized query construction they share. Everything is **driven by the flow
registry** (`flows.yaml`) — table, year column, entity columns, and a metric's
measure column + aggregation (SUM for premium, AVG for score) all come from the
registry, so the same primitive serves GPR and survey with no hardcoded names.

Safety: column names cannot be bound parameters, so every identifier is checked
against the flow's declared columns (`safe_column`) before it is interpolated;
values are always passed as bound parameters. This is the injection + no-
hallucinated-column guard.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from core.registry import get_flow_registry
from core.registry.spec import FlowSpec, MetricSpec


def flow_spec(flow: str) -> FlowSpec:
    """The registry spec for `flow`, or a ValueError for an unknown flow."""
    spec = get_flow_registry().get(flow)
    if spec is None:
        raise ValueError(f"unknown flow {flow!r}")
    return spec


def _allowlist(spec: FlowSpec) -> set:
    """Every column name the flow declares — the identifier allowlist."""
    return set(spec.columns)


def safe_column(spec: FlowSpec, column: str) -> str:
    """Return `column` iff the flow declares it; else raise (injection guard)."""
    if column not in _allowlist(spec):
        raise ValueError(f"unknown column {column!r} for flow {spec.name}")
    return column


def find_metric(spec: FlowSpec, metric: str) -> Optional[MetricSpec]:
    """Resolve a metric by canonical name or alias (case-insensitive)."""
    if not metric:
        return None
    direct = spec.metric(metric)
    if direct:
        return direct
    needle = metric.strip().lower()
    for name, mspec in spec.metrics.items():
        if name.lower() == needle or needle in {a.lower() for a in mspec.aliases}:
            return mspec
    return None


def resolve_measure(spec: FlowSpec, metric: str) -> Tuple[str, str]:
    """(measure column, aggregation) for `metric` — e.g. ('Premium','SUM').

    Falls back to SUM when a (derived) metric declares no aggregation, since the
    underlying measure for the premium-derived metrics is an additive SUM.
    """
    mspec = find_metric(spec, metric)
    if mspec is None or not mspec.columns:
        raise ValueError(f"unknown metric {metric!r} for flow {spec.name}")
    return mspec.columns[0], (mspec.default_aggregation or "SUM").upper()


def where_clause(
    spec: FlowSpec, filters: Dict[str, Any], params: Dict[str, Any]
) -> str:
    """Build a parametrized WHERE from `filters`, appending binds to `params`.

    Text values are compared case-insensitively (the GPR/survey rule); numeric
    values (e.g. Year) compared directly. Returns "" for no filters.
    """
    clauses: List[str] = []
    for i, (column, value) in enumerate(filters.items()):
        col = safe_column(spec, column)
        # Multi-value filter → IN (...). Empty collection = no constraint.
        if isinstance(value, (list, tuple, set)):
            vals = list(value)
            if not vals:
                continue
            keys = []
            for j, v in enumerate(vals):
                k = f"f{i}_{j}"
                params[k] = v
                keys.append(f":{k}")
            if all(isinstance(v, str) for v in vals):  # case-insensitive text match
                placeholders = ", ".join(f"LOWER({k})" for k in keys)
                clauses.append(f'LOWER("{col}") IN ({placeholders})')
            else:
                clauses.append(f'"{col}" IN ({", ".join(keys)})')
            continue
        key = f"f{i}"
        if isinstance(value, bool):  # guard: bool is an int subclass
            clauses.append(f'"{col}" = :{key}')
        elif isinstance(value, str):
            clauses.append(f'LOWER("{col}") = LOWER(:{key})')
        else:
            clauses.append(f'"{col}" = :{key}')
        params[key] = value
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def run_rows(engine: Any, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute `sql` with bound `params` and return rows as plain dicts."""
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]


def resolve_engine(engine: Optional[Any]) -> Any:
    """Use the injected engine, else lazily the process engine (production)."""
    if engine is not None:
        return engine
    from core.initialization import Initialization  # lazy: avoid LLM/init import

    return Initialization.engine
