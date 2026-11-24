"""Where the turn's separately-made decisions contradict each other.

Each rule is a plain function of the spec returning a `Disagreement` or None,
and `RULES` lists them — adding a rule is one function and one line. A
disagreement is not an error today (shadow mode); it is the measurement of
how often the current pipeline is told two things at once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

from core.analysis.operation import MOVEMENT, PENETRATION, PERFORMANCE, POSITION
from core.turn.spec import TurnSpec

#: Operations no single query can answer (same set the depth floor uses).
MULTI_QUERY_OPERATIONS = frozenset({PERFORMANCE, PENETRATION, MOVEMENT, POSITION})

#: Shapes whose writer contract asks for several grouped sections.
MULTI_SECTION_SHAPES = frozenset(
    {"analyst", "driver", "briefing", "advisory", "comparison"}
)


@dataclass(frozen=True)
class Disagreement:
    """Two decisions about one turn that cannot both be right."""

    rule: str
    between: str
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


def lookup_route_owes_requirements(spec: TurnSpec) -> Disagreement | None:
    """Sent down the single-query rail, yet its operation owes a full contract.

    A plain lookup or breakdown owes one value or one GROUP BY, which the rail
    serves; only the multi-query operations are a contradiction there.
    """
    if (
        spec.depth == "lookup"
        and spec.operation in MULTI_QUERY_OPERATIONS
        and spec.requirements
    ):
        return Disagreement(
            "lookup_route_owes_requirements",
            "depth vs operation",
            f"depth=lookup but '{spec.operation}' requires {', '.join(spec.requirements)}",
        )
    return None


def shape_exceeds_depth(spec: TurnSpec) -> Disagreement | None:
    """The writer is asked for grouped sections the evidence plan cannot fill."""
    if (
        spec.depth == "lookup"
        and spec.shape in MULTI_SECTION_SHAPES
        and spec.presentation == "prose"
    ):
        return Disagreement(
            "shape_exceeds_depth",
            "depth vs shape",
            f"shape={spec.shape} asks for a multi-section answer from one query",
        )
    return None


def direct_shape_on_analyst_route(spec: TurnSpec) -> Disagreement | None:
    """A one-line answer paid for with a full multi-lens analysis."""
    if spec.depth == "analytical" and spec.shape == "direct":
        return Disagreement(
            "direct_shape_on_analyst_route",
            "depth vs shape",
            "shape=direct (one line) but depth=analytical runs the full analyst",
        )
    return None


def restriction_outside_family(spec: TurnSpec) -> Disagreement | None:
    """The question limited the datasets to ones its route cannot reach."""
    if (
        spec.family in {"premium", "survey"}
        and spec.sources
        and spec.sources != (("gpr",) if spec.family == "premium" else ("survey",))
    ):
        return Disagreement(
            "restriction_outside_family",
            "family vs question",
            f"family={spec.family} but the question restricts to {', '.join(spec.sources)}",
        )
    return None


def unresolved_terms_routed(spec: TurnSpec) -> Disagreement | None:
    """Names the user typed that matched nothing, reaching routing unasked."""
    if spec.unresolved:
        return Disagreement(
            "unresolved_terms_routed",
            "filters vs clarification",
            f"unresolved: {', '.join(spec.unresolved)}",
        )
    return None


def fallback_with_scope(spec: TurnSpec) -> Disagreement | None:
    """Filters resolved, yet the turn is routed as off-topic."""
    if spec.family == "fallback" and spec.scope:
        return Disagreement(
            "fallback_with_scope",
            "family vs filters",
            f"family=fallback with filters on {', '.join(c for c, _ in spec.scope)}",
        )
    return None


Rule = Callable[[TurnSpec], Disagreement | None]

RULES: tuple[Rule, ...] = (
    lookup_route_owes_requirements,
    shape_exceeds_depth,
    direct_shape_on_analyst_route,
    restriction_outside_family,
    unresolved_terms_routed,
    fallback_with_scope,
)


def find_disagreements(
    spec: TurnSpec, rules: tuple[Rule, ...] = RULES
) -> tuple[Disagreement, ...]:
    """Every rule that fires for this spec, in rule order."""
    return tuple(d for d in (rule(spec) for rule in rules) if d is not None)
