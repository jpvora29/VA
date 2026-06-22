"""Studio data access — engine resolution + DB-derived filter options.

LLM-free on purpose: this never imports ``core.initialization`` (which builds the
Azure/dspy clients). It resolves a SQLite engine from the same ``DB_PATH`` the live
app uses, falling back to a deterministic seed DB for local dev. Filter dropdown
options come straight from the DB (DISTINCT per column), so the form always
reflects the real data — no dependency on the legacy ``config`` package.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List

from sqlalchemy import create_engine, text

from core.registry import get_flow_registry
from logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_engine():
    """The Studio SQLite engine.

    Order: ``STUDIO_DB_PATH`` → ``DB_PATH`` (the live app's DB) → a local seed DB
    built on first use. The seed path keeps dev/CI runnable without the production
    data while exercising the exact same primitives.
    """
    path = os.getenv("STUDIO_DB_PATH") or os.getenv("DB_PATH")
    if path:
        logger.info("studio: using DB at %s", path)
        return create_engine(f"sqlite:///{path}")
    from studio.seed import ensure_seed_db

    seed = ensure_seed_db()
    logger.info("studio: no DB_PATH set; using seed DB at %s", seed)
    return create_engine(f"sqlite:///{seed}")


_OPTION_CAP = 100_000  # effectively "all" for a dropdown, but bounds a pathological column


def _distinct(engine, table: str, column: str, limit: int = _OPTION_CAP) -> List[Any]:
    # Cap the scan at the SQL layer: on a huge table we only need enough distinct
    # values to populate a dropdown, and we never want to materialise millions.
    sql = (
        f'SELECT v FROM (SELECT DISTINCT "{column}" AS v FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL) ORDER BY v LIMIT {int(limit)}'
    )
    try:
        with engine.connect() as conn:
            return [r.v for r in conn.execute(text(sql)).fetchall()]
    except Exception as exc:  # noqa: BLE001 - a missing column must not break the form
        logger.debug("distinct(%s.%s) failed: %s", table, column, exc)
        return []


@lru_cache(maxsize=128)
def _distinct_cached(table: str, column: str, limit: int = _OPTION_CAP) -> tuple:
    """Process-lifetime cache of a column's distinct values (the singleton engine).

    Distinct values are stable for a session, so the expensive scan runs once per
    column — the rest of the run is instant. Returns a tuple so it stays hashable.
    """
    return tuple(_distinct(get_engine(), table, column, limit))


@lru_cache(maxsize=256)
def _distinct_where(table: str, column: str, where_key: tuple, limit: int = _OPTION_CAP) -> tuple:
    """Cached distinct `column` values constrained by `where_key` (parametrised IN).

    `where_key` is a hashable tuple of ``(col, (v1, v2, …))`` pairs — the cascade
    constraints (e.g. Country values for a chosen Region)."""
    clauses = [f'"{column}" IS NOT NULL']
    params: Dict[str, Any] = {}
    for i, (col, vals) in enumerate(where_key):
        ph = []
        for j, v in enumerate(vals):
            k = f"w{i}_{j}"
            params[k] = v
            ph.append(f":{k}")
        clauses.append(f'"{col}" IN ({", ".join(ph)})')
    sql = (
        f'SELECT v FROM (SELECT DISTINCT "{column}" AS v FROM "{table}" '
        f'WHERE {" AND ".join(clauses)}) ORDER BY v LIMIT {int(limit)}'
    )
    try:
        with get_engine().connect() as conn:
            return tuple(r.v for r in conn.execute(text(sql), params).fetchall())
    except Exception as exc:  # noqa: BLE001
        logger.debug("distinct_where(%s.%s) failed: %s", table, column, exc)
        return ()


def dependent_options(
    flow: str, column: str, where: Dict[str, Any] | None = None
) -> List[Dict[str, Any]]:
    """`[{label, value}]` for `column`, optionally constrained by upstream selections.

    Columns are validated against the flow registry (injection guard). With no
    constraint this is the full (cached) distinct list — so it also serves the
    "give me the entire carrier list" case."""
    spec = get_flow_registry().get(flow)
    if spec is None or column not in spec.columns:
        return []
    pairs = []
    for col, val in (where or {}).items():
        if col not in spec.columns:
            continue
        vals = val if isinstance(val, (list, tuple, set)) else [val]
        vals = tuple(v for v in vals if v not in (None, "", "all", "All"))
        if vals:
            pairs.append((col, vals))
    key = tuple(sorted(pairs))
    values = (
        _distinct_where(spec.primary_table, column, key)
        if key
        else _distinct_cached(spec.primary_table, column)
    )
    return [{"label": str(v), "value": v} for v in values]


def filter_options(flow: str, *, engine=None) -> Dict[str, List[Dict[str, Any]]]:
    """`{column: [{label, value}]}` for every entity/temporal column of the flow.

    Driven by the flow registry so it stays in lock-step with the schema. Distinct
    values are cached per column (``_distinct_cached``) so a huge table is scanned
    once per column, not on every page load.
    """
    spec = get_flow_registry().get(flow)
    if spec is None:
        return {}
    cols = [c.name for c in spec.columns.values() if c.role in {"entity", "temporal"}]
    options: Dict[str, List[Dict[str, Any]]] = {}
    for col in cols:
        values = _distinct_cached(spec.primary_table, col)
        if values:
            options[col] = [{"label": str(v), "value": v} for v in values]
    return options


@lru_cache(maxsize=4)
def cached_filter_options(flow: str) -> Dict[str, List[Dict[str, Any]]]:
    """Memoised `filter_options` for the lazy boot callback — built at most once."""
    return filter_options(flow)
