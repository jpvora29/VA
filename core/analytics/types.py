"""Core value objects for the deterministic analytics library.

These are the typed contracts every primitive speaks — settled once here so the
rest of the build (timeframe resolution, the primitive library, the planner
orchestrator, the boardroom cutover) plugs in without re-litigating shapes. See
`core/deterministic_analytics_plan.md` for the full design.

The guiding rule: **the LLM never produces a number that exists in the data.**
A primitive computes a number deterministically and returns it as an
`AnalyticsFact` — value plus the provenance (`support` rows, `formula`) needed to
ground it in narration and surface it in the UI.

Everything here is plain stdlib + dataclasses: no dspy, no DB, no API keys — so
the contracts (and the primitives that speak them) stay unit-testable in
isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

Number = Union[int, float]


@dataclass(frozen=True)
class AnalyticsFact:
    """One computed scalar plus the provenance needed to ground and display it.

    `dims` is the cut the fact is for (e.g. ``{"carrier": "Zurich",
    "product": "Cyber"}``); `support` is the exact rows the number was computed
    from (handed to the UI as evidence); `formula` is the human-readable
    definition used (for the grounding eval and audit trails).
    """

    name: str
    value: Number
    unit: str = ""
    rendered: str = ""
    dims: Mapping[str, Any] = field(default_factory=dict)
    support: List[Dict[str, Any]] = field(default_factory=list)
    formula: str = ""

    @property
    def dims_key(self) -> Tuple[Tuple[str, str], ...]:
        """Stable, hashable key for this fact's cut.

        Composite analyzers use it to align facts from different tier-1
        primitives that describe the *same* slice (e.g. carrier premium vs
        market premium for ``product=Cyber``).
        """
        return tuple(sorted((str(k), str(v)) for k, v in self.dims.items()))


@dataclass(frozen=True)
class PrimitiveArgs:
    """What to compute and over which cuts — dimension- and flow-agnostic.

    A primitive never hard-codes dimension names. `group_by` and `filters` are
    open and validated against the flow's ``valid_values`` at query time, so the
    SAME `compute_rank` ranks carriers by premium across ``Product_Line`` OR by
    score across ``Attribute`` — the caller supplies the columns, the primitive
    supplies the math.
    """

    flow: str
    metric: str = ""
    group_by: Tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)
    subject: Optional[str] = None
    peers: Optional[Tuple[str, ...]] = None

    def cache_key(self) -> Tuple[Any, ...]:
        """Hashable identity for ``(primitive, args)`` memoisation."""
        return (
            self.flow,
            self.metric,
            tuple(self.group_by),
            tuple(sorted(self.filters.items())),
            self.subject,
            tuple(self.peers) if self.peers else None,
        )


@dataclass(frozen=True)
class FactFrame:
    """A thin, normalized read-only view over result rows already in state.

    Holds the rows plus the column→role map detected by ``frame.build_frame``.
    Primitives ask for columns by *role* (``"temporal"``, ``"premium"`` …) rather
    than by hardcoded name, which is what keeps them flow-agnostic.
    """

    rows: Tuple[Dict[str, Any], ...] = ()
    roles: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)

    def columns(self, role: str) -> Tuple[str, ...]:
        """Columns present in the data that carry the given role."""
        return tuple(self.roles.get(role, ()))

    def distinct(self, role: str) -> set:
        """Distinct non-empty values across every column with this role."""
        values: set = set()
        for col in self.columns(role):
            for row in self.rows:
                val = row.get(col)
                if val not in (None, ""):
                    values.add(str(val).strip())
        return values


# A primitive is a pure function: (frame, args) -> fact(s). Kept as a bare
# Callable alias (not an ABC) so plain functions register directly — dictionary
# dispatch over a registry, no class ceremony.
PrimitiveFn = Callable[[FactFrame, PrimitiveArgs], Union[AnalyticsFact, List[AnalyticsFact]]]


@dataclass(frozen=True)
class CompositePrimitive:
    """A tier-2 analyzer that answers a multi-metric question by composing tier-1
    primitives through the registry — never by re-deriving their math.

    It declares its `depends_on` (tier-1 names) so the registry can inject them,
    and `combine` owns ONLY the composing rule (e.g. whitespace's "carrier ~0 AND
    market present"). Swapping how a dependency is computed leaves `combine`
    untouched.
    """

    name: str
    depends_on: Tuple[str, ...]
    combine: Callable[..., List[AnalyticsFact]]
