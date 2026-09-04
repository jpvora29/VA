"""Composite indexes for the analytics warehouse.

A Studio build reads the warehouse a few thousand times: every sub-deck asks for
its scope's totals, its rank, its share of wallet, its peer benchmark and its
per-dimension decomposition, and each of those is a filtered aggregate. On a
table with no usable index every one of them is a full scan, so the build's cost
is (queries x rows) rather than (queries x log rows).

Measured on the 152k-row seed book, four representative analytics queries:

    no indexes                              356 ms
    single-column, per filter column         80 ms
    + one composite (Country, Year, Carrier_Group)   39 ms

and the worst single query went from 83 ms to 0.84 ms. The gap grows with the
table, because a scan grows with the table and an index lookup does not.

**Why composite and not the single-column indexes we already had.** SQLite uses
at most one index per table per query, so a single-column index on ``Country``
still leaves it scanning every row of that country to apply the carrier and year
filters. The composite matches the whole WHERE clause, and carrying the measure
as the last column makes it *covering* — the query is answered from the index
without touching the table at all.

**Why the shapes are roles, not column names.** ``_SHAPES`` names registry roles
(carrier, country, product, year), so the same plan serves GPR and survey and
follows a schema rename instead of breaking on one.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import text

from core.registry import get_flow_registry
from logger import get_logger

logger = get_logger(__name__)

# Index name prefix, so ours are recognisable and `missing` can tell what exists.
_PREFIX = "ix_studio"

# The filter shapes a build actually issues, as registry ROLES, most-selective
# leading column first. Each is completed with the flow's measure column, which
# makes the index covering for a filtered aggregate.
#
#   1. one carrier, one country, one year   — every subject scope
#   2. the whole market for a country/year  — the Marsh denominator, and the
#                                             carrier ranking that groups by carrier
#   3/4. the same market slice cut by product / segment — the breakdown pages
_SHAPES: Tuple[Tuple[str, ...], ...] = (
    ("carrier", "country", "year"),
    ("country", "year", "carrier"),
    ("country", "year", "product"),
    ("country", "year", "segment"),
)


@dataclass(frozen=True)
class IndexSpec:
    """One index to create: its name, its table, and its columns in order."""

    name: str
    table: str
    columns: Tuple[str, ...]

    def create_sql(self) -> str:
        cols = ", ".join(f'"{c}"' for c in self.columns)
        return f'CREATE INDEX IF NOT EXISTS "{self.name}" ON "{self.table}" ({cols})'


def _year_column(spec: Any) -> Optional[str]:
    """The flow's YEAR column — the temporal column a build filters on.

    Matched on the name ENDING in "year", so both GPR's ``Year`` and survey's
    ``Survey_Year`` resolve. Not every temporal column qualifies: ``Billing_Date``
    has row-level grain and would make an index as large as the table for no
    selectivity gain, and ``Month_Name`` is not a scope a build filters by.
    """
    for name, column in spec.columns.items():
        if column.role == "temporal" and name.lower().endswith("year"):
            return name
    return None


def _measure_column(spec: Any) -> Optional[str]:
    """The measure to carry as the index's last column, making it covering.

    The flow's FIRST DECLARED METRIC, not the first measure-role column: survey
    declares four measures (``ResponseCount``, ``Responses``, ``Score``,
    ``NPS Score``) and only the one its metrics are built on is worth carrying.
    Falls back to any measure column for a flow that declares no metric.
    """
    for metric in spec.metrics.values():
        if metric.columns and metric.columns[0] in spec.columns:
            return metric.columns[0]
    for name, column in spec.columns.items():
        if column.role == "measure":
            return name
    return None


def _columns_for(spec: Any, shape: Sequence[str]) -> Tuple[str, ...]:
    """Resolve a role shape to real column names, or () when the flow lacks one."""
    year = _year_column(spec)
    resolved: List[str] = []
    for role in shape:
        column = year if role == "year" else spec.entity_columns.get(role)
        if not column or column not in spec.columns:
            return ()
        resolved.append(column)
    return tuple(resolved)


def index_plan(flow: str = "gpr") -> Tuple[IndexSpec, ...]:
    """Every index this flow should have, in creation order.

    A shape the flow cannot satisfy (no such role, or no year column) is dropped
    rather than approximated — a half-matching index costs write time and buys
    nothing.
    """
    spec = get_flow_registry().get(flow)
    if spec is None:
        return ()
    measure = _measure_column(spec)
    plan: List[IndexSpec] = []
    seen: set = set()
    for shape in _SHAPES:
        columns = _columns_for(spec, shape)
        if not columns:
            continue
        if measure:  # covering: the aggregate never has to touch the table
            columns = (*columns, measure)
        if columns in seen:
            continue
        seen.add(columns)
        plan.append(
            IndexSpec(
                name=f"{_PREFIX}_{spec.primary_table}_{'_'.join(shape)}".lower(),
                table=spec.primary_table,
                columns=columns,
            )
        )
    return tuple(plan)


def existing_indexes(engine: Any, table: str) -> frozenset:
    """Index names already on `table` (ours and anyone else's)."""
    sql = "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=:t"
    try:
        with engine.connect() as conn:
            return frozenset(r[0] for r in conn.execute(text(sql), {"t": table}))
    except Exception as exc:  # noqa: BLE001 - a non-SQLite engine simply opts out
        logger.debug("studio: cannot list indexes on %s: %s", table, exc)
        return frozenset()


def missing_indexes(flow: str, engine: Any) -> Tuple[IndexSpec, ...]:
    """The planned indexes this database does not have yet.

    Cheap — one read of ``sqlite_master`` — so it is safe on the hot path. It is
    what makes `ensure_indexes` a no-op on every launch after the first.
    """
    plan = index_plan(flow)
    if not plan:
        return ()
    have = existing_indexes(engine, plan[0].table)
    return tuple(spec for spec in plan if spec.name not in have)


def auto_index_enabled() -> bool:
    """``STUDIO_AUTO_INDEX=off`` opts out of building indexes on first use.

    On by default. Indexing is the difference between a build in minutes and a
    build in hours, so a read-only or externally-managed warehouse has to say so
    rather than pay that silently.
    """
    return os.getenv("STUDIO_AUTO_INDEX", "on").strip().lower() != "off"


def ensure_indexes(flow: str = "gpr", engine: Any = None) -> List[str]:
    """Create any missing planned index. Returns the names actually created.

    One-time per database: the first call pays for the build, every later call
    costs one ``sqlite_master`` read. Failures are logged and swallowed — a
    warehouse we may not write to must still be queryable, just slower.
    """
    if engine is None:
        from studio.data import get_engine

        engine = get_engine()
    pending = missing_indexes(flow, engine)
    if not pending:
        return []

    made: List[str] = []
    started = time.time()
    for spec in pending:
        try:
            with engine.begin() as conn:
                conn.execute(text(spec.create_sql()))
            made.append(spec.name)
        except Exception as exc:  # noqa: BLE001 - never let indexing break a build
            logger.warning("studio: index %s failed: %s", spec.name, exc)
    if made:
        logger.info(
            "studio: built %d analytics index(es) in %.1fs — one-time for this database",
            len(made),
            time.time() - started,
        )
    return made
