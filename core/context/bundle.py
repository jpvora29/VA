"""Typed context bundle with per-audience views (decisions #1, #4).

`ContextBundle` is the single artifact the ContextEngine produces per turn. It
holds the raw, fully-resolved context once; each node then takes only *its*
slice through a `for_*()` view, so no node sees more than it needs. The headline
example: routing and the solver must NOT receive the full schema dump or the full
valid_values dict — those were the two biggest prompt-bloat offenders. The views
make that structural, not a matter of each caller remembering to trim.

Views are tiny frozen dataclasses (not dicts) so a leak — e.g. the routing view
gaining `valid_values` — is a visible field addition caught by
`tests/context/test_bundle_views.py`, not a silent dict key.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.context.retriever import ResolvedValues

# Schema column metadata uses the "Column Name" key (see core/mcp/tools.py).
_COLUMN_NAME_KEY = "Column Name"


def _schema_outline(schema_tables: Dict[str, Any]) -> Dict[str, List[str]]:
    """table -> [column names] — structure only, no metadata, no values."""
    outline: Dict[str, List[str]] = {}
    for table, cols in (schema_tables or {}).items():
        names = []
        for col in cols or []:
            if isinstance(col, dict):
                name = col.get(_COLUMN_NAME_KEY)
                if name:
                    names.append(name)
        outline[table] = names
    return outline


# --------------------------------------------------------------------------- #
# Per-audience views — each exposes only its slice.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RoutingView:
    """Cheapest view: just enough to pick a flow/table family. No values."""

    flow: str
    query: str
    schema_outline: Dict[str, List[str]]


@dataclass(frozen=True)
class PlannerView:
    flow: str
    query: str
    schema_tables: Dict[str, Any]
    definitions: Dict[str, str]
    valid_values: Dict[str, List[str]]  # already cardinality-gated / resolved
    valid_year_quarter: List[str]
    rules: str
    routing_context: Any


@dataclass(frozen=True)
class SQLView:
    flow: str
    query: str
    schema_tables: Dict[str, Any]
    valid_values: Dict[str, List[str]]
    valid_year_quarter: List[str]
    rules: str


@dataclass(frozen=True)
class SolverView:
    """Analyst-solver view (step 5): grounded slice, no full schema/values dump."""

    flow: str
    query: str
    schema_outline: Dict[str, List[str]]
    resolved_entities: Dict[str, List[str]]
    rules: str


@dataclass(frozen=True)
class ResponseView:
    flow: str
    query: str
    definitions: Dict[str, str]
    rules: str


@dataclass(frozen=True)
class ContextBundle:
    """All context for one turn; nodes consume `for_*()` slices, not the whole."""

    flow: str
    query: str
    schema_tables: Dict[str, Any] = field(default_factory=dict)
    definitions: Dict[str, str] = field(default_factory=dict)
    valid_values: Dict[str, List[str]] = field(default_factory=dict)
    resolved_entities: Dict[str, ResolvedValues] = field(default_factory=dict)
    skills: Dict[str, str] = field(default_factory=dict)  # scope -> rendered body
    valid_year_quarter: List[str] = field(default_factory=list)
    routing_context: Any = None

    def _rules(self, scope: str) -> str:
        return self.skills.get(scope) or ""

    def _resolved_lists(self) -> Dict[str, List[str]]:
        return {col: rv.values for col, rv in self.resolved_entities.items() if rv.values}

    def for_routing(self) -> RoutingView:
        return RoutingView(
            flow=self.flow,
            query=self.query,
            schema_outline=_schema_outline(self.schema_tables),
        )

    def for_planner(self) -> PlannerView:
        return PlannerView(
            flow=self.flow,
            query=self.query,
            schema_tables=self.schema_tables,
            definitions=self.definitions,
            valid_values=self.valid_values,
            valid_year_quarter=self.valid_year_quarter,
            rules=self._rules("planner"),
            routing_context=self.routing_context,
        )

    def for_sql(self) -> SQLView:
        return SQLView(
            flow=self.flow,
            query=self.query,
            schema_tables=self.schema_tables,
            valid_values=self.valid_values,
            valid_year_quarter=self.valid_year_quarter,
            rules=self._rules("sql"),
        )

    def for_solver(self) -> SolverView:
        return SolverView(
            flow=self.flow,
            query=self.query,
            schema_outline=_schema_outline(self.schema_tables),
            resolved_entities=self._resolved_lists(),
            rules=self._rules("sql"),
        )

    def for_response(self) -> ResponseView:
        return ResponseView(
            flow=self.flow,
            query=self.query,
            definitions=self.definitions,
            rules=self._rules("response"),
        )
