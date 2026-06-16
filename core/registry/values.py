"""DB-distinct value registry (decisions doc #2).

A cached `SELECT DISTINCT` per categorical column — the runtime source of column
*values*, mirroring the per-engine schema cache in `core/data/general.py`. The
flow registry owns the *semantics* (role, card_cap); this owns the *values*.

Generalizes the ad-hoc `_DISTINCT_CACHE` / `get_distinct_values` in
`core/mcp/tools.py`. The engine is injectable (`engine_provider`) so the module
imports WITHOUT credentials and unit tests can point it at an in-memory SQLite
DB; in production it lazily reads `Initialization.engine`.

Only verified schema identifiers are ever interpolated into SQL — the column is
checked against the live table columns before the query is built.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import inspect, text

from core.registry.loader import get_flow_registry
from logger import get_logger

logger = get_logger(__name__)


def _sorted_years(values: List[str]) -> List[str]:
    """Sort year-ish values ascending: numerically when possible, else lexically.

    Year columns are typically stored as integers, but degrade gracefully if a
    flow's year column ever holds non-numeric periods.
    """
    def key(value: str) -> Tuple[int, Any]:
        try:
            return (0, int(value))
        except (TypeError, ValueError):
            return (1, str(value))

    return sorted(values, key=key)


@dataclass
class DistinctValueRegistry:
    """Cached distinct-value lookups, keyed by (table, column)."""

    engine_provider: Optional[Callable[[], Any]] = None
    _cache: Dict[Tuple[str, str], List[str]] = field(default_factory=dict, init=False)

    def _engine(self) -> Any:
        if self.engine_provider is not None:
            return self.engine_provider()
        from core.initialization import Initialization  # lazy: avoid LLM import

        return Initialization.engine

    def distinct(self, table: str, column: str) -> List[str]:
        """Distinct non-null values of `column` in `table` (cached).

        Returns [] for an unknown table/column — the same injection guard the
        former `get_distinct_values` used.
        """
        key = (table, column)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        engine = self._engine()
        try:
            columns = {c["name"] for c in inspect(engine).get_columns(table)}
        except Exception:  # noqa: BLE001 - unknown table -> empty, never raise
            self._cache[key] = []
            return []
        if column not in columns:
            self._cache[key] = []
            return []

        # `table`/`column` are verified schema identifiers (not user input);
        # double-quoted for SQLite.
        sql = (
            f'SELECT DISTINCT "{column}" AS v FROM "{table}" '
            f'WHERE "{column}" IS NOT NULL ORDER BY "{column}"'
        )
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(sql)).fetchall()
            values = [str(row[0]) for row in rows]
        except Exception as exc:  # noqa: BLE001 - degrade to empty on any DB error
            logger.debug("distinct(%s.%s) failed: %s", table, column, exc)
            values = []
        self._cache[key] = values
        return values

    def for_flow_column(self, flow: str, column: str) -> List[str]:
        """Distinct values of `column`, searching the flow's allowed tables.

        Uses the first allowed table that actually contains the column.
        """
        spec = get_flow_registry().get(flow)
        if spec is None:
            return []
        for table in spec.allowed_tables:
            values = self.distinct(table, column)
            if values:
                return values
        return []

    def valid_years(self, flow: str) -> List[str]:
        """Distinct years for `flow`, ascending so the latest is the LAST element.

        The runtime, data-sourced replacement for the hardcoded
        ``valid_year_quarter_* / valid_years_*`` lists in
        ``config/valid_values_config.py``: it reads the flow's declared year
        column (registry ``date_columns['year']`` — ``Year`` for GPR, ``Survey_Year``
        for survey) and returns its distinct values sorted numerically. The
        ascending order matches the contract the planner's ``valid_year_quarter``
        input documents ("the most recent period is the last element").
        """
        spec = get_flow_registry().get(flow)
        if spec is None:
            return []
        year_column = spec.date_columns.get("year")
        if not year_column:
            return []
        return _sorted_years(self.for_flow_column(flow, year_column))

    def refresh(self) -> None:
        """Drop the cache (e.g. after the warehouse data changes)."""
        self._cache.clear()


_default_registry: Optional[DistinctValueRegistry] = None


def get_distinct_registry() -> DistinctValueRegistry:
    """Process-wide singleton (production engine)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = DistinctValueRegistry()
    return _default_registry
