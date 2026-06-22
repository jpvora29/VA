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


def _distinct(engine, table: str, column: str, limit: int = 500) -> List[Any]:
    sql = f'SELECT DISTINCT "{column}" AS v FROM "{table}" WHERE "{column}" IS NOT NULL ORDER BY v'
    try:
        with engine.connect() as conn:
            return [r.v for r in conn.execute(text(sql)).fetchall()][:limit]
    except Exception as exc:  # noqa: BLE001 - a missing column must not break the form
        logger.debug("distinct(%s.%s) failed: %s", table, column, exc)
        return []


def filter_options(flow: str, *, engine=None) -> Dict[str, List[Dict[str, Any]]]:
    """`{column: [{label, value}]}` for every entity/temporal column of the flow.

    Driven by the flow registry so it stays in lock-step with the schema; values
    are read live from the DB.
    """
    engine = engine or get_engine()
    spec = get_flow_registry().get(flow)
    if spec is None:
        return {}
    cols = [c.name for c in spec.columns.values() if c.role in {"entity", "temporal"}]
    options: Dict[str, List[Dict[str, Any]]] = {}
    for col in cols:
        values = _distinct(engine, spec.primary_table, col)
        if values:
            options[col] = [{"label": str(v), "value": v} for v in values]
    return options
