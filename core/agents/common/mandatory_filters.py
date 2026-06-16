"""Mandatory-filter gate — the deterministic Carrier+Country requirement check.

Architecture doc §1 Layer 1: HITL fires only when a MANDATORY filter is still
missing after history inheritance + fuzzy resolution. The mandatory set is
**Carrier + Country**; timeframe is excluded because it always auto-defaults to
the latest years.

This component has ONE job (SRP): decide which mandatory roles are still missing
for a turn. It does NOT build clarify questions — that is the
`MandatoryFilterSource` in `core.graph.hitl`, which turns each
`FilterRequirement` into an MCQ. Keeping the decision pure makes it trivially
testable and reusable.

Columns are derived from the flow registry's `entity_columns` (the SAME source
`resolve_entities` writes `resolved_filters` from), so a satisfied role is
detected against the exact column the contract would have filled — no drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple

from core.agents.common.contract import resolved_filters_of, unresolved_terms_of
from core.registry import get_flow_registry

# table_family -> flows whose schema columns the mandatory roles live in. Mirrors
# `contract._FLOWS_BY_FAMILY`; fallback/unknown families never gate.
_FLOWS_BY_FAMILY = {
    "premium": ("gpr",),
    "survey": ("survey",),
    "both": ("gpr", "survey"),
}

# The mandatory roles, in ask order. Carrier (who) before Country (where).
_MANDATORY_ROLES: Tuple[str, ...] = ("carrier", "country")

# role -> the RoutingContext field carrying an inherited value for that role. An
# inherited value satisfies the requirement (a follow-up that inherits the
# carrier must NOT re-ask for it).
_INHERITED_FIELD = {
    "carrier": "inherited_carrier",
    "country": "inherited_country",
}


@dataclass(frozen=True)
class FilterRequirement:
    """A mandatory role the turn is missing and must clarify."""

    role: str  # "carrier" | "country"
    columns: Tuple[str, ...]  # candidate schema columns across the family's flows
    flow: str  # flow whose valid values seed the clarify options
    label: str  # short chip header, e.g. "Carrier"


class MandatoryFilterGate:
    """Decides which mandatory filters (Carrier + Country) are still missing.

    The registry is injected (DI) so tests can pass a stub flow registry instead
    of the production one.
    """

    def __init__(self, *, registry: Any = None, flows_by_family: dict = _FLOWS_BY_FAMILY) -> None:
        self._registry = registry if registry is not None else get_flow_registry()
        self._flows_by_family = flows_by_family

    def _columns_for(self, family: str, role: str) -> Tuple[str, ...]:
        """The schema columns a role maps to across the family's flows (registry
        `entity_columns`), de-duplicated and in flow order."""
        columns: List[str] = []
        for flow in self._flows_by_family.get(family, ()):
            spec = self._registry.get(flow)
            if spec is None:
                continue
            column = (getattr(spec, "entity_columns", None) or {}).get(role)
            if column and column not in columns:
                columns.append(column)
        return tuple(columns)

    def missing_mandatory_filters(self, routing_context: Any) -> List[FilterRequirement]:
        """The mandatory roles this turn still lacks, in ask order.

        A role is SATISFIED when the contract already resolved a value into any of
        its columns OR a value was inherited from history. When neither holds, the
        role is missing UNLESS the user named it but it failed to resolve — that
        mention surfaces as an unresolved term and is handled by the grounded
        "did you mean…?" source, so we defer to it instead of double-asking.
        """
        if routing_context is None:
            return []
        family = (getattr(routing_context, "table_family", "") or "").lower()
        if family not in self._flows_by_family:  # fallback / out-of-scope
            return []

        resolved = resolved_filters_of(routing_context)
        unresolved_kinds = {
            getattr(term, "kind", "") for term in unresolved_terms_of(routing_context)
        }

        missing: List[FilterRequirement] = []
        for role in _MANDATORY_ROLES:
            columns = self._columns_for(family, role)
            if not columns:
                continue
            if any(resolved.get(column) for column in columns):
                continue  # already resolved to an exact value
            if getattr(routing_context, _INHERITED_FIELD[role], None):
                continue  # inherited from a prior turn
            if role in unresolved_kinds:
                continue  # named-but-unresolved -> the "did you mean" source owns it
            primary_flow = next(iter(self._flows_by_family.get(family, ())), "")
            missing.append(
                FilterRequirement(
                    role=role,
                    columns=columns,
                    flow=primary_flow,
                    label=role.title(),
                )
            )
        return missing
