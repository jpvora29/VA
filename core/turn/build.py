"""Assemble a `TurnSpec` from the decisions the graph has already made.

Pure: reads the routing context and the question, calls only deterministic
helpers (operation detector, requirement library, directive readers). No model
call, so shadow mode costs nothing per turn.
"""

from __future__ import annotations

from typing import Any

from core.agents.common.contract import resolved_filters_of, unresolved_terms_of
from core.agents.common.directives import answer_shape, presentation_mode
from core.analysis.alignment import QUARTER, available_grains
from core.analysis.operation import detect_operation, detect_source_restriction
from core.analysis.requirements import (
    GPR,
    SURVEY,
    EvidenceContract,
    Requirement,
    RequirementLibrary,
    build_contract,
    get_requirements,
)
from core.turn.spec import Scope, TurnSpec

#: Datasets each routing family may draw on.
FAMILY_SOURCES = {
    "premium": (GPR,),
    "survey": (SURVEY,),
    "both": (GPR, SURVEY),
    "fallback": (),
}

_PERIOD_COLUMNS = ("Year", "Quarter", "Year_Quarter", "Month_Name", "Date")


def build_turn_spec(question: str, routing_context: Any) -> TurnSpec:
    """The turn's interpretation, read off what each component decided."""
    family = _field(routing_context, "table_family", "fallback")
    depth = _field(routing_context, "analysis_depth", "lookup")
    operation = detect_operation(question, depth=depth)
    sources = turn_sources(question, family)
    contract = build_contract(
        operation, conditions=turn_conditions(family, sources), allowed_sources=sources
    )
    scope = scope_of(routing_context)
    return TurnSpec(
        question=question,
        family=family,
        depth=depth,
        operation=operation,
        shape=answer_shape(routing_context),
        presentation=presentation_mode(routing_context),
        sources=sources,
        requirements=contract.keys(),
        deferred=tuple(r.key for r in contract.deferred),
        scope=scope,
        inherited=inherited_of(routing_context),
        unresolved=unresolved_of(routing_context),
        period_named=period_named(scope, routing_context),
    )


def spec_contract(
    spec: TurnSpec, library: RequirementLibrary | None = None
) -> EvidenceContract:
    """The evidence contract the spec recorded, rebuilt from its keys."""
    library = library or get_requirements()
    return EvidenceContract(
        spec.operation,
        requirements_of(library, spec.requirements),
        requirements_of(library, spec.deferred),
    )


def requirements_of(
    library: RequirementLibrary, keys: tuple[str, ...]
) -> tuple[Requirement, ...]:
    return tuple(r for r in map(library.requirement, keys) if r is not None)


def turn_sources(question: str, family: str) -> tuple[str, ...]:
    """The family's datasets, narrowed by an explicit "premium only"."""
    allowed = FAMILY_SOURCES.get(family, ())
    restricted = detect_source_restriction(question)
    if restricted:
        return tuple(s for s in allowed if s in restricted) or restricted
    return allowed


def turn_conditions(family: str, sources: tuple[str, ...]) -> tuple[str, ...]:
    """Conditions knowable before retrieval (mirrors the analyst's own rule)."""
    conditions = []
    if SURVEY in sources and family in {"both", "survey"}:
        conditions.append("comparable_survey_data")
    if QUARTER in available_grains(GPR):
        conditions.append("quarterly_data_available")
    return tuple(conditions)


def scope_of(routing_context: Any) -> Scope:
    filters = resolved_filters_of(routing_context)
    return tuple(
        sorted(
            (str(k), tuple(str(v) for v in (vals or ()))) for k, vals in filters.items()
        )
    )


def inherited_of(routing_context: Any) -> tuple[tuple[str, str], ...]:
    pairs = []
    for name in ("carrier", "country", "year", "metric"):
        value = _field(routing_context, f"inherited_{name}", None)
        if value:
            pairs.append((name, str(value)))
    return tuple(pairs)


def unresolved_of(routing_context: Any) -> tuple[str, ...]:
    terms = []
    for term in unresolved_terms_of(routing_context):
        text = (
            term.get("term") if isinstance(term, dict) else getattr(term, "term", term)
        )
        if text:
            terms.append(str(text))
    return tuple(terms)


def period_named(scope: Scope, routing_context: Any) -> bool:
    """Whether the question (or its inheritance) fixed a period."""
    if any(column in _PERIOD_COLUMNS for column, _ in scope):
        return True
    return bool(_field(routing_context, "inherited_year", None))


def _field(obj: Any, name: str, default: Any) -> Any:
    if obj is None:
        return default
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    return default if value in (None, "") else value
