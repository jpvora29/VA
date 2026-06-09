"""Typed, read-only flow-registry specs.

A `FlowSpec` is the declarative description of one data family (survey / gpr /
gimmi): which tables it grounds against, its date/entity columns, its metrics and
their aliases, per-column *semantics* (role, cardinality cap, definition,
confidentiality, aliases), and chart defaults. **Values come from the DB at
runtime; semantics come from here.**

This is the shared foundation the decisions doc calls the "central flow
registry": it feeds dynamic valid_values (the cardinality gate reads
`card_cap`/`role`), the ContextEngine collector, and the chart critic.

Specs are immutable. `valid_values()` / `definitions()` resolve a dotted python
pointer (`valid_values_source` / `definitions_source` in `flows.yaml`) lazily, so
in this first step the registry *reads* today's `GetValidData` dicts rather than
duplicating them — a pure, parity-tested seam. `schema(engine)` slices the live
DB schema down to this flow's allowed tables.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Column roles drive both the cardinality gate (step 3) and the chart critic's
# field typing (step 8). Kept as plain strings (not an Enum) so the YAML stays
# the single source of truth and unknown roles surface in `validate()`.
COLUMN_ROLES = frozenset(
    {"entity", "measure", "temporal", "continuous", "filter"}
)

DEFAULT_CARD_CAP = 30


def _resolve_object(dotted: str) -> Any:
    """Resolve a dotted path like ``core.data.valid_values.GetValidData.valid_values``.

    Imports the longest importable module prefix, then walks the remaining
    attribute chain (class, then class attribute). Lazy by design: the registry
    must not pull the data layer at import time.
    """
    parts = dotted.split(".")
    module = None
    attr_parts: List[str] = []
    # Find the longest prefix that imports as a module.
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        try:
            module = importlib.import_module(candidate)
            attr_parts = parts[i:]
            break
        except ModuleNotFoundError:
            continue
    if module is None:  # pragma: no cover - misconfigured pointer
        raise ImportError(f"Cannot resolve any module prefix of {dotted!r}")
    obj: Any = module
    for name in attr_parts:
        obj = getattr(obj, name)
    return obj


@dataclass(frozen=True)
class ColumnSpec:
    """Per-column semantics. Values are *not* stored here — only meaning."""

    name: str
    role: str  # entity | measure | temporal | continuous | filter
    card_cap: int = DEFAULT_CARD_CAP
    definition: str = ""
    confidential: bool = False
    aliases: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricSpec:
    """A metric and the columns / aggregation / synonyms that define it."""

    name: str
    columns: Tuple[str, ...]
    default_aggregation: str = ""
    aliases: Tuple[str, ...] = ()
    derived: bool = False


@dataclass(frozen=True)
class FlowSpec:
    """Immutable description of one data family."""

    name: str
    label: str
    route_label: str
    pitch_eligible: bool
    primary_table: str
    supporting_tables: Tuple[str, ...]
    allowed_tables: Tuple[str, ...]
    date_columns: Dict[str, str]
    entity_columns: Dict[str, str]
    metrics: Dict[str, MetricSpec]
    columns: Dict[str, ColumnSpec]
    chart_measure_priority: Tuple[str, ...]
    chart_dimension_priority: Tuple[str, ...]
    peer_names_allowed: bool
    valid_values_source: str = ""
    definitions_source: str = ""

    # ---- runtime data (resolved lazily) ----------------------------------

    def valid_values(self) -> Dict[str, Any]:
        """Valid column values for this flow (resolved from the data layer)."""
        if not self.valid_values_source:
            return {}
        return _resolve_object(self.valid_values_source)

    def definitions(self) -> Dict[str, str]:
        """Business definitions for this flow's columns."""
        if not self.definitions_source:
            return {}
        return _resolve_object(self.definitions_source)

    def schema(self, engine: Any) -> Dict[str, list]:
        """Live DB schema sliced to this flow's allowed tables.

        Imported lazily to avoid a registry -> data-layer import cycle.
        """
        from core.data.general import GeneralFunctions

        full = GeneralFunctions.get_database_schema(engine=engine)
        return {table: full.get(table, []) for table in self.allowed_tables}

    # ---- semantic helpers -------------------------------------------------

    def metric(self, name: str) -> Optional[MetricSpec]:
        return self.metrics.get(name)

    def column(self, name: str) -> Optional[ColumnSpec]:
        return self.columns.get(name)

    def card_cap(self, column: str) -> int:
        spec = self.columns.get(column)
        return spec.card_cap if spec else DEFAULT_CARD_CAP

    def columns_by_role(self, role: str) -> List[str]:
        return [c.name for c in self.columns.values() if c.role == role]

    def resolve_alias(self, term: str) -> Optional[str]:
        """Map a user term to a metric or column name via declared aliases.

        Exact case-insensitive match against metric names, column names, and
        their `aliases`. Returns the canonical name, or None.
        """
        needle = (term or "").strip().lower()
        if not needle:
            return None
        for metric in self.metrics.values():
            if needle == metric.name.lower() or needle in {
                a.lower() for a in metric.aliases
            }:
                return metric.name
        for col in self.columns.values():
            if needle == col.name.lower() or needle in {
                a.lower() for a in col.aliases
            }:
                return col.name
        return None

    def pitch_filter_columns(self) -> List[str]:
        """Entity columns usable as Pitch Builder filters."""
        return list(self.entity_columns.values())
