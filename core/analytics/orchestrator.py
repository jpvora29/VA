"""Analytics orchestrator (Phase 3): run a plan's primitive calls deterministically.

Given the primitive calls the planner selected (or a lens bundle — Phase 3.5), this
dispatches each over the library `LIBRARY`, merges the turn's shared scope filters,
computes each fact once (cached by `(name, args)`), and collects everything into a
typed `EvidenceSet`. A call whose primitive is unknown or which raises is recorded
in `skipped` — the signal for the caller to fall through to the existing LLM-SQL
path for that piece. One failing primitive never sinks the turn.

Dependency-light by design: calls are duck-typed (a `PrimitiveCall` model OR a plain
dict), so this module imports no dspy/LLM layer and unit-tests against an in-memory
DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from core.analytics.library import LIBRARY
from core.analytics.types import AnalyticsFact, PrimitiveArgs
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class EvidenceSet:
    """The computed facts for one turn, plus what fell back to LLM-SQL."""

    facts: List[AnalyticsFact] = field(default_factory=list)
    by_call: Dict[str, List[AnalyticsFact]] = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)  # unknown/failed -> LLM-SQL fallback

    def values(self) -> List[Any]:
        """Flat list of computed values — handy for the grounding eval (Phase 5)."""
        return [fact.value for fact in self.facts]


def _get(call: Any, key: str, default: Any) -> Any:
    """Read a field from a duck-typed call (model attribute or dict key)."""
    if isinstance(call, dict):
        return call.get(key, default)
    return getattr(call, key, default)


class AnalyticsOrchestrator:
    """Dispatches primitive calls over the library. `library` is injectable."""

    def __init__(self, *, library: Mapping[str, Any] = LIBRARY) -> None:
        self._library = library

    def run(
        self,
        calls: Optional[Sequence[Any]],
        *,
        flow: str,
        shared_filters: Optional[Mapping[str, Any]] = None,
        engine: Any = None,
    ) -> EvidenceSet:
        """Run each call; collect facts. Unknown/failed calls go to `skipped`.

        `shared_filters` is the turn's scope (e.g. carrier + country + year) applied
        to every call; a call's own `filters` take precedence on key collisions.
        """
        evidence = EvidenceSet()
        cache: Dict[Any, List[AnalyticsFact]] = {}
        for call in calls or []:
            name = _get(call, "name", None)
            primitive = self._library.get(name) if name else None
            if primitive is None:
                if name:
                    evidence.skipped.append(name)
                continue

            args = PrimitiveArgs(
                flow=flow,
                metric=_get(call, "metric", "") or "",
                group_by=tuple(_get(call, "group_by", ()) or ()),
                filters={**(shared_filters or {}), **(_get(call, "filters", {}) or {})},
            )

            key = (name, args.cache_key())
            result = cache.get(key)
            if result is None:
                try:
                    result = list(primitive(args, engine=engine))
                except Exception as exc:  # noqa: BLE001 - one primitive must not sink the turn
                    logger.debug("primitive %s failed: %s", name, exc)
                    evidence.skipped.append(name)
                    continue
                cache[key] = result

            evidence.by_call.setdefault(name, []).extend(result)
            evidence.facts.extend(result)
        return evidence
