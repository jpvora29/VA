"""Flow-registry loader — parses `flows.yaml` into immutable `FlowSpec`s.

Module-level singleton mirroring `core.skills.loader.get_skill_loader()`, so the
parsed registry is built once per process. `flow_registry.get(flow)` is the
read-only entry point used by `core/mcp/tools.py`, the dynamic valid_values gate,
the ContextEngine, and the chart critic.

`validate()` is the CI guard: every metric/entity column must appear in the
`columns` block, and every column role must be a known role.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.registry.spec import (
    COLUMN_ROLES,
    DEFAULT_CARD_CAP,
    RESOLVERS,
    ColumnSpec,
    FlowSpec,
    MetricSpec,
)
from logger import get_logger

logger = get_logger(__name__)

_REGISTRY_PATH = Path(__file__).parent / "flows.yaml"


def _as_tuple(value: Any) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _parse_metric(name: str, raw: Dict[str, Any]) -> MetricSpec:
    return MetricSpec(
        name=name,
        columns=_as_tuple(raw.get("columns")),
        default_aggregation=str(raw.get("default_aggregation", "")),
        aliases=_as_tuple(raw.get("aliases")),
        derived=bool(raw.get("derived", False)),
    )


def _parse_column(name: str, raw: Dict[str, Any]) -> ColumnSpec:
    return ColumnSpec(
        name=name,
        role=str(raw.get("role", "")),
        card_cap=int(raw.get("card_cap", DEFAULT_CARD_CAP)),
        definition=str(raw.get("definition", "")),
        confidential=bool(raw.get("confidential", False)),
        aliases=_as_tuple(raw.get("aliases")),
        resolver=str(raw.get("resolver", "fuzzy")),
    )


def _parse_flow(name: str, raw: Dict[str, Any]) -> FlowSpec:
    tables = raw.get("tables", {}) or {}
    chart = raw.get("chart_defaults", {}) or {}
    confidentiality = raw.get("confidentiality", {}) or {}
    return FlowSpec(
        name=name,
        label=str(raw.get("label", name)),
        route_label=str(raw.get("route_label", name)),
        pitch_eligible=bool(raw.get("pitch_eligible", False)),
        primary_table=str(tables.get("primary", "")),
        supporting_tables=_as_tuple(tables.get("supporting")),
        allowed_tables=_as_tuple(raw.get("allowed_tables")),
        date_columns=dict(raw.get("date_columns", {}) or {}),
        entity_columns=dict(raw.get("entity_columns", {}) or {}),
        metrics={
            m_name: _parse_metric(m_name, m_raw or {})
            for m_name, m_raw in (raw.get("metrics", {}) or {}).items()
        },
        columns={
            c_name: _parse_column(c_name, c_raw or {})
            for c_name, c_raw in (raw.get("columns", {}) or {}).items()
        },
        chart_measure_priority=_as_tuple(chart.get("measure_priority")),
        chart_dimension_priority=_as_tuple(chart.get("dimension_priority")),
        peer_names_allowed=bool(confidentiality.get("peer_names_allowed", False)),
        valid_values_source=str(raw.get("valid_values_source", "")),
        definitions_source=str(raw.get("definitions_source", "")),
    )


@dataclass
class FlowRegistry:
    """Parsed `flows.yaml`, served on demand."""

    path: Path = _REGISTRY_PATH
    _flows: Dict[str, FlowSpec] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self._flows = {name: _parse_flow(name, body) for name, body in raw.items()}

    def get(self, flow: str) -> Optional[FlowSpec]:
        return self._flows.get(flow)

    def flows(self) -> List[str]:
        return list(self._flows)

    def __contains__(self, flow: str) -> bool:
        return flow in self._flows

    def validate(self) -> List[str]:
        """Return registry-health issues (empty == healthy). For a CI test."""
        issues: List[str] = []
        for name, flow in self._flows.items():
            known_cols = set(flow.columns)
            for col in flow.columns.values():
                if col.role not in COLUMN_ROLES:
                    issues.append(
                        f"{name}: column {col.name!r} has unknown role {col.role!r}"
                    )
                if col.resolver not in RESOLVERS:
                    issues.append(
                        f"{name}: column {col.name!r} has unknown resolver "
                        f"{col.resolver!r}"
                    )
                if col.is_semantic and col.role != "entity":
                    issues.append(
                        f"{name}: column {col.name!r} is resolver=semantic but "
                        f"role={col.role!r} (semantic resolution is entity-only)"
                    )
            for role, col in flow.entity_columns.items():
                if col not in known_cols:
                    issues.append(
                        f"{name}: entity column {col!r} ({role}) missing from `columns`"
                    )
            for metric in flow.metrics.values():
                for col in metric.columns:
                    if col not in known_cols:
                        issues.append(
                            f"{name}: metric {metric.name!r} references "
                            f"undeclared column {col!r}"
                        )
            if not flow.allowed_tables:
                issues.append(f"{name}: no allowed_tables")
        return issues


_default_registry: Optional[FlowRegistry] = None


def get_flow_registry() -> FlowRegistry:
    """Module-level singleton so the parsed registry is reused across requests."""
    global _default_registry
    if _default_registry is None:
        _default_registry = FlowRegistry()
    return _default_registry
