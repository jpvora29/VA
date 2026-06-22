"""The ``@cut`` catalog and the per-request scoped registry.

A **cut** is one named, deterministic analysis unit the user can switch on (e.g.
"Top 5 industries", "Whitespace", "Share of Wallet"). Each cut is a thin recipe
over the ``core/analytics`` primitive library — it owns *which* numbers to compute
for a page, never the math.

Design (see ``studio/DESIGN.md`` §2):

- ``@cut(...)`` records a cut into a module-level ``CATALOG`` — the ergonomic
  decorator registration requested. This is the ONLY global mutation, and it is
  metadata only (it never executes anything at import time).
- At request time the page calls ``build_scoped_registry(selected_names)`` to get a
  ``ScopedRegistry`` containing ONLY the cuts the user selected. The runtime scope
  (not the import-time catalog) is what gates execution — so "only the selected
  functions run" holds, and tests build isolated scopes without touching globals,
  staying consistent with ``core/analytics``' no-global-mutation posture.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from core.analytics.types import AnalyticsFact

# ── context handed to every cut ─────────────────────────────────────────────


@dataclass(frozen=True)
class CutContext:
    """Everything a cut needs to compute, supplied per request.

    ``filters`` is the form's resolved scope (carrier/country/year/…) keyed by the
    flow's real column names. ``engine`` is injectable so cuts unit-test against an
    in-memory DB (defaulting lazily to the process engine inside the primitives).
    """

    flow: str
    filters: Mapping[str, Any] = field(default_factory=dict)
    engine: Any = None
    options: Mapping[str, Any] = field(default_factory=dict)


# A cut is a pure-ish function: (ctx) -> facts. Bare Callable alias, no ABC —
# dictionary dispatch over the catalog, no class ceremony (mirrors PrimitiveFn).
CutFn = Callable[[CutContext], List[AnalyticsFact]]


@dataclass(frozen=True)
class CutSpec:
    """Metadata + the callable for one registered cut."""

    name: str
    fn: CutFn
    flow: str  # "gpr" | "survey"
    page: str  # "overall" | "industry" | "country" | "product" | "rank" | "peer"
    label: str
    requires: Tuple[str, ...] = ()  # filter keys this cut needs to be meaningful
    tags: Tuple[str, ...] = ()

    def run(self, ctx: CutContext) -> List[AnalyticsFact]:
        return list(self.fn(ctx))


class UnknownCutError(KeyError):
    """Raised when a selected cut name is not in the catalog."""


# ── the catalog (decorator target) ──────────────────────────────────────────

CATALOG: Dict[str, CutSpec] = {}


def cut(
    name: str,
    *,
    flow: str,
    page: str,
    label: str,
    requires: Tuple[str, ...] = (),
    tags: Tuple[str, ...] = (),
) -> Callable[[CutFn], CutFn]:
    """Register ``fn`` as a selectable cut. Returns ``fn`` unchanged.

    Registration is metadata only — importing a cut module never computes
    anything. Duplicate names are a programming error and raise immediately.
    """

    def decorator(fn: CutFn) -> CutFn:
        if name in CATALOG:
            raise ValueError(f"duplicate cut name {name!r}")
        CATALOG[name] = CutSpec(
            name=name,
            fn=fn,
            flow=flow,
            page=page,
            label=label,
            requires=tuple(requires),
            tags=tuple(tags),
        )
        return fn

    return decorator


def catalog() -> Mapping[str, CutSpec]:
    """Read-only view of every registered cut (e.g. to build the form's toggles)."""
    return dict(CATALOG)


def cuts_for(*, flow: Optional[str] = None, page: Optional[str] = None) -> List[CutSpec]:
    """Catalog entries filtered by flow and/or page — drives the page's checkboxes."""
    return [
        spec
        for spec in CATALOG.values()
        if (flow is None or spec.flow == flow) and (page is None or spec.page == page)
    ]


# ── per-request scoped registry (only selected cuts execute) ────────────────


class ScopedRegistry:
    """A request-scoped collection holding ONLY the user-selected cuts.

    The orchestration layer runs ``run_all`` over this scope; cuts outside the
    selection are not present and therefore cannot execute.
    """

    def __init__(self, specs: Mapping[str, CutSpec]) -> None:
        self._specs: Dict[str, CutSpec] = dict(specs)

    def names(self) -> Tuple[str, ...]:
        return tuple(sorted(self._specs))

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def get(self, name: str) -> CutSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise UnknownCutError(name) from exc

    def run(self, name: str, ctx: CutContext) -> List[AnalyticsFact]:
        return self.get(name).run(ctx)

    def run_all(self, ctx: CutContext) -> Dict[str, List[AnalyticsFact]]:
        """Run every scoped cut; return ``{cut_name: facts}``.

        One failing cut must not sink the page — callers decide how to surface a
        cut that returns no facts; this method simply skips a cut that raises is
        left to the orchestrator (kept thin here on purpose).
        """
        return {name: spec.run(ctx) for name, spec in self._specs.items()}


def build_scoped_registry(names: Tuple[str, ...]) -> ScopedRegistry:
    """Build a scope containing exactly ``names`` from the global catalog.

    Unknown names raise ``UnknownCutError`` — a selection must reference real cuts.
    """
    selected: Dict[str, CutSpec] = {}
    for name in names:
        if name not in CATALOG:
            raise UnknownCutError(name)
        selected[name] = CATALOG[name]
    return ScopedRegistry(selected)
