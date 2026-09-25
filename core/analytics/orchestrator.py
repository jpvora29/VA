"""Analytics orchestrator (Phase 3): run a plan's primitive calls deterministically.

Given the primitive calls the planner selected (or a lens bundle — Phase 3.5), this
dispatches each over the library `LIBRARY`, merges the turn's shared scope filters,
computes each fact once (cached by `(name, args)`), and collects everything into a
typed `EvidenceSet`. A call whose primitive is unknown or which raises is recorded
in `skipped` — the signal for the caller to fall through to the existing LLM-SQL
path for that piece. One failing primitive never sinks the turn.

Dependency-light by design: calls are duck-typed (a `PrimitiveCall` model OR a plain
dict), so this module imports no LLM layer and unit-tests against an in-memory
DB.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from core.analytics.library import LIBRARY
from core.analytics.types import AnalyticsFact, PrimitiveArgs, freeze_items
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


def useful_group_by(
    group_by: Sequence[str], filters: Mapping[str, Any]
) -> Tuple[str, ...]:
    """`group_by` minus any column the filters already pin to a single value.

    Cutting by a column the question already fixed produces a table with one row
    that repeats the filter back — "share of wallet for Property, by product
    line" is one row reading "Property". The reader asked for a figure and was
    handed a one-row table of it.

    The selector is a model choosing `group_by` from the question's wording, and
    "for Property" reads to it as both a filter and an axis. Which of the two it
    is, is not a judgement call: a filter pinned to one value cannot also be a
    cut. `core.analytics.dimensions.choose_dimension` applies the same rule to
    the position table, which is why that one already steps down to industry.
    """
    from core.analytics.dimensions import pinned_columns

    fixed = pinned_columns(filters)
    return tuple(column for column in group_by if column not in fixed)


@lru_cache(maxsize=None)
def _tuning_parameters(primitive: Callable) -> Tuple[str, ...]:
    """The keyword-only tuning arguments a primitive accepts (`grain`, `top_n`…).

    Read off the signature so a call's `options` can be passed through without the
    orchestrator carrying a per-primitive table; anything the primitive does not
    declare is dropped rather than raising.
    """
    try:
        parameters = inspect.signature(primitive).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins/stubs
        return ()
    return tuple(
        name
        for name, parameter in parameters.items()
        if name not in {"args", "engine"}
        and parameter.kind is inspect.Parameter.KEYWORD_ONLY
    )


def _supported_options(primitive: Callable, options: Mapping[str, Any]) -> Dict[str, Any]:
    """`options` narrowed to what this primitive declares."""
    if not options:
        return {}
    accepted = _tuning_parameters(primitive)
    return {key: value for key, value in options.items() if key in accepted}


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
        subject: Optional[str] = None,
        peers: Optional[Sequence[str]] = None,
    ) -> EvidenceSet:
        """Run each call; collect facts. Unknown/failed calls go to `skipped`.

        `shared_filters` is the turn's scope (e.g. carrier + country + year) applied
        to every call; a call's own `filters` take precedence on key collisions.
        `subject` names the entity in focus and `peers` pins a hand-picked peer set
        (the UI's custom-peer override), so peer primitives benchmark against
        exactly that set instead of resolving the `Peers` table.
        """
        evidence = EvidenceSet()
        cache: Dict[Any, List[AnalyticsFact]] = {}
        pinned = tuple(peers) if peers else None
        for call in calls or []:
            name = _get(call, "name", None)
            primitive = self._library.get(name) if name else None
            if primitive is None:
                if name:
                    evidence.skipped.append(name)
                continue

            merged = {**(shared_filters or {}), **(_get(call, "filters", {}) or {})}
            asked = tuple(_get(call, "group_by", ()) or ())
            cuts = useful_group_by(asked, merged)
            if cuts != asked:
                logger.info(
                    "dropped a redundant cut from %s: %s is already pinned by the scope",
                    name, ", ".join(c for c in asked if c not in cuts),
                )
            args = PrimitiveArgs(
                flow=flow,
                metric=_get(call, "metric", "") or "",
                group_by=cuts,
                filters=merged,
                subject=subject,
                peers=pinned,
            )
            options = _supported_options(primitive, _get(call, "options", {}) or {})

            # `freeze_items` on both halves: an option value can be a list too,
            # and this lookup is outside the try/except below.
            key = (name, args.cache_key(), freeze_items(options))
            result = cache.get(key)
            if result is None:
                try:
                    result = list(primitive(args, engine=engine, **options))
                except Exception as exc:  # noqa: BLE001 - one primitive must not sink the turn
                    logger.debug("primitive %s failed: %s", name, exc)
                    evidence.skipped.append(name)
                    continue
                cache[key] = result

            evidence.by_call.setdefault(name, []).extend(result)
            evidence.facts.extend(result)
        return evidence
