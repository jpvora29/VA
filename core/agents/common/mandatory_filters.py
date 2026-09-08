"""Mandatory-filter gate — is this turn scoped by anything at all?

Architecture doc §1 Layer 1: HITL fires only when a MANDATORY filter is still
missing after history inheritance + fuzzy resolution.

**The bar is ANY of carrier, country or year — not all of them.** Requiring both
carrier AND country meant a question that named a carrier was still stopped to be
asked for a country, and a question that named a year and a country was stopped
for a carrier. A turn that states any one of the three has told us what it is
about; the analyst can answer it, and the zero-row guard catches a scope that
turns out to be empty. Only a turn that names NONE of them — "how are we doing?"
with no history to inherit from — has nothing to run.

That deliberately makes this gate quiet. It is not the only way to reach a human:
an entity the contract could not match still asks "did you mean...?", and the
ambiguity classifier still fires on a genuinely unclear question. Those are
clarifications about MEANING, and they are independent of whether a filter is
present (see `core.graph.hitl`).

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

import re
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

# Any ONE of these being present means the turn is scoped and runs. `period` has
# no clarify question of its own (it auto-defaults to the latest years), but a
# question that names a year IS scoped, so it counts as satisfying the gate.
_SCOPING_ROLES: Tuple[str, ...] = ("carrier", "country", "period")

# role -> the RoutingContext field carrying an inherited value for that role. An
# inherited value satisfies the requirement (a follow-up that inherits the
# carrier must NOT re-ask for it).
_INHERITED_FIELD = {
    "carrier": "inherited_carrier",
    "country": "inherited_country",
    "period": "inherited_year",
}

# A resolved filter on one of these columns is a year the user asked for.
_PERIOD_COLUMN = re.compile(r"(?i)year|quarter|month|period")

# role -> the `entities` field a raw mention lands in. A named-but-unresolved
# carrier still says what the question is about, so it scopes the turn even
# though it did not become a filter.
_ENTITY_FIELD = {
    "carrier": "carriers",
    "country": "countries",
    "period": "years",
}


def _values_in(entities: Any, field: str) -> bool:
    """True when an entity bucket holds at least one non-blank mention.

    `entities` is a `QueryEntities` model in production and a plain dict in
    tests, so both shapes are read the same way.
    """
    values = entities.get(field) if isinstance(entities, dict) else getattr(entities, field, None)
    return any(str(v).strip() for v in (values or []))


@dataclass(frozen=True)
class FilterRequirement:
    """A mandatory role the turn is missing and must clarify."""

    role: str  # "carrier" | "country"
    columns: Tuple[str, ...]  # candidate schema columns across the family's flows
    flow: str  # flow whose valid values seed the clarify options
    label: str  # short chip header, e.g. "Carrier"


class MandatoryFilterGate:
    """Decides whether a turn is scoped enough to run, and what to ask if not.

    Two questions, in order: `has_scope` — does the turn name any of carrier,
    country or year? — and, only when it does not, `missing_mandatory_filters` —
    which of carrier/country can we usefully ask for?

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

    def has_scope(self, routing_context: Any) -> bool:
        """True when the turn names (or inherits) a carrier, a country or a year.

        Resolution is not required. A carrier the user named that failed to match
        still says what the question is about — the "did you mean…?" source owns
        that mismatch, and stopping to ask "which carrier?" on top of it asks the
        same thing twice.
        """
        if routing_context is None:
            return False
        family = (getattr(routing_context, "table_family", "") or "").lower()
        resolved = resolved_filters_of(routing_context)
        entities = getattr(routing_context, "entities", None) or {}
        for role in _SCOPING_ROLES:
            if any(resolved.get(column) for column in self._columns_for(family, role)):
                return True
            if getattr(routing_context, _INHERITED_FIELD[role], None):
                return True
            if _values_in(entities, _ENTITY_FIELD[role]):
                return True
        if str(getattr(routing_context, "timeframe_hint", "") or "").strip():
            return True
        # A resolved year has no `entity_columns` role of its own (the registry
        # maps country/carrier/product/segment), so it is matched by column name.
        return any(
            values and _PERIOD_COLUMN.search(str(column))
            for column, values in resolved.items()
        )

    def missing_mandatory_filters(self, routing_context: Any) -> List[FilterRequirement]:
        """The mandatory roles to ask for — empty unless the turn has NO scope.

        A turn scoped by any of carrier / country / year runs as asked. Only a
        turn scoped by none of them is stopped, and then it is asked for the roles
        it can actually be asked for (carrier, then country), skipping any the
        user named but the data could not match — that mention surfaces as an
        unresolved term and the grounded "did you mean…?" source owns it.
        """
        if routing_context is None:
            return []
        family = (getattr(routing_context, "table_family", "") or "").lower()
        if family not in self._flows_by_family:  # fallback / out-of-scope
            return []
        if self.has_scope(routing_context):
            return []

        unresolved_kinds = {
            getattr(term, "kind", "") for term in unresolved_terms_of(routing_context)
        }

        missing: List[FilterRequirement] = []
        for role in _MANDATORY_ROLES:
            columns = self._columns_for(family, role)
            if not columns:
                continue
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
