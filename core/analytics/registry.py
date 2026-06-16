"""Dictionary-dispatch registry for analytics primitives (DI-friendly).

The registry is the single dispatch point the orchestrator (Phase 3) calls into:
``registry.run("compute_rank", frame, args)``. It is a plain map of name →
primitive function, so:

- new primitives register by adding to a dict — no inheritance, no plugin magic;
- tests build an isolated registry with stub primitives injected, never touching
  any global;
- composite analyzers receive the registry by dependency injection and pull their
  tier-1 dependencies through it.

There is no import-time global mutation. The default registry is built explicitly
from `primitives.BUILTINS` via `build_default_registry` (see ``__init__``), which
keeps construction order obvious and testable.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple, Union

from core.analytics.types import AnalyticsFact, FactFrame, PrimitiveArgs, PrimitiveFn


class UnknownPrimitiveError(KeyError):
    """Raised when a name is not registered. The orchestrator catches this to
    fall through to the LLM-SQL path rather than failing the turn."""


class AnalyticsRegistry:
    """A mutable-by-construction, dispatch-by-name collection of primitives.

    Inject a `primitives` map to build a scoped registry (e.g. in tests); call
    `register` to add more. Lookups are by exact name.
    """

    def __init__(self, primitives: Optional[Mapping[str, PrimitiveFn]] = None) -> None:
        self._fns: Dict[str, PrimitiveFn] = dict(primitives or {})

    def register(self, name: str, fn: PrimitiveFn) -> None:
        """Add (or replace) a primitive under `name`."""
        self._fns[name] = fn

    def has(self, name: str) -> bool:
        return name in self._fns

    def __contains__(self, name: object) -> bool:
        return name in self._fns

    def names(self) -> Tuple[str, ...]:
        """Registered primitive names, sorted — handy for the planner allowlist."""
        return tuple(sorted(self._fns))

    def get(self, name: str) -> PrimitiveFn:
        try:
            return self._fns[name]
        except KeyError as exc:
            raise UnknownPrimitiveError(name) from exc

    def run(
        self, name: str, frame: FactFrame, args: PrimitiveArgs
    ) -> Union[AnalyticsFact, List[AnalyticsFact]]:
        """Dispatch to the named primitive and return its fact(s)."""
        return self.get(name)(frame, args)
