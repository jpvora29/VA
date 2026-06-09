"""ContextEngine — the single, deterministic context assembler (decisions #1, #4).

ONE engine, one pass per turn, **zero extra model calls on the common path**:

    collector  -> raw schema / definitions / valid_values / skill bodies
    retriever  -> resolve high-card columns (fuzzy-first, LLM-rescue hybrid)
    reranker   -> deterministic weighted ordering          (interface stubbed)
    compressor -> extractive selection                     (interface stubbed)
    injection  -> cardinality-gate the values into the bundle
    -> ContextBundle (per-audience views)

The retriever is the only place a model can be involved, and only as a *rescue*:
fuzzy resolution is tried first, the LLM fires only when fuzzy misses on a
registry `resolver: semantic` column and `CONTEXT_ENGINE_SEMANTIC` is on. So a
typical lookup turn builds the whole bundle with no LLM call.

Rollout is flag-gated and planner-first (`CONTEXT_ENGINE_PLANNER`), shadow before
cutover — same discipline as the step-3 gate. Default off = callers keep their
existing context path untouched.
"""
from __future__ import annotations

import os
from typing import Any, Optional, Sequence

from core.context.bundle import ContextBundle
from core.context.collector import DEFAULT_SCOPES, collect
from core.context.injection import assemble_valid_values
from core.context.retriever import EntityResolver, build_resolver
from core.registry import get_flow_registry
from logger import get_logger

logger = get_logger(__name__)


def engine_enabled() -> bool:
    """True when the planner/context_filler should consume the engine bundle."""
    return os.getenv("CONTEXT_ENGINE_PLANNER", "off").lower() in {"on", "shadow"}


def shadow_mode() -> bool:
    """True when the engine runs alongside the legacy path for diffing only."""
    return os.getenv("CONTEXT_ENGINE_PLANNER", "off").lower() == "shadow"


class ContextEngine:
    """Builds a `ContextBundle` for one turn. Resolver is injectable for tests."""

    def __init__(self, *, resolver_factory=build_resolver) -> None:
        self._resolver_factory = resolver_factory

    def build(
        self,
        flow: str,
        query: str,
        *,
        routing_context: Any = None,
        valid_year_quarter: Optional[Sequence[str]] = None,
        scopes: Sequence[str] = DEFAULT_SCOPES,
        resolver: Optional[EntityResolver] = None,
        **collect_overrides: Any,
    ) -> ContextBundle:
        """Assemble the full context bundle for `flow` + `query`."""
        raw = collect(flow, query, scopes=scopes, **collect_overrides)

        spec = get_flow_registry().get(flow)
        caps = (
            {col: spec.card_cap(col) for col in raw.full_valid_values}
            if spec is not None
            else {}
        )
        resolver = resolver or self._resolver_factory(flow)

        gated, resolved = assemble_valid_values(
            raw.full_valid_values, query, card_caps=caps, resolver=resolver
        )

        return ContextBundle(
            flow=flow,
            query=query,
            schema_tables=raw.schema_tables,
            definitions=raw.definitions,
            valid_values=gated,
            resolved_entities=resolved,
            skills=raw.skills,
            valid_year_quarter=list(valid_year_quarter or []),
            routing_context=routing_context,
        )
