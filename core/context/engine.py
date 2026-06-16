"""ContextEngine — the single, deterministic context assembler (decisions #1, #4).

ONE engine, one pass per turn, **zero extra model calls on the common path**.

Pipeline legend (Phase 0 Fix 3) — every stage `build()` runs, in order, with its
input → output and whether it does real work in v1:

    stage        method                  input -> output                  v1
    ---------    ---------------------   ------------------------------   --------
    collector    collect_raw_context     (flow, query) -> RawContext      active
    retriever    resolve_entities        RawContext -> _ResolvedContext   active
    reranker     rank_candidates         _ResolvedContext -> (same)       identity
    compressor   compress                _ResolvedContext -> (same)       identity
    gate         gate_valid_values       _ResolvedContext -> gated dict   active
    values       resolve_valid_years     flow -> [years] (from the DB)    active
    bundle       assemble_bundle         gated dict -> ContextBundle      active

The retriever is the only place a model can be involved, and only as a *rescue*:
fuzzy resolution is tried first, the LLM fires only when fuzzy misses on a
registry `resolver: semantic` column and `CONTEXT_ENGINE_SEMANTIC` is on. So a
typical lookup turn builds the whole bundle with no LLM call.

The reranker and compressor are reserved seams (decision #12): they are wired as
visible **identity** stages, not missing steps — a future model rerank /
abstractive compression slots in behind the same method with no orchestration
change. Per-audience injection is the `ContextInjector` (`core/context/injector.py`),
applied downstream when each node consumes its slice.

Rollout is flag-gated and planner-first (`CONTEXT_ENGINE_PLANNER`), shadow before
cutover — same discipline as the step-3 gate. Default off = callers keep their
existing context path untouched.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

from core.context.bundle import ContextBundle
from core.context.collector import DEFAULT_SCOPES, RawContext, collect
from core.context.gate import gate_with_resolved, resolve_high_card
from core.context.retriever import EntityResolver, ResolvedValues, build_resolver
from core.registry import get_flow_registry
from logger import get_logger

logger = get_logger(__name__)


def engine_enabled() -> bool:
    """True when the planner/context_filler should consume the engine bundle."""
    return os.getenv("CONTEXT_ENGINE_PLANNER", "off").lower() in {"on", "shadow"}


def shadow_mode() -> bool:
    """True when the engine runs alongside the legacy path for diffing only."""
    return os.getenv("CONTEXT_ENGINE_PLANNER", "off").lower() == "shadow"


@dataclass
class _ResolvedContext:
    """Working state threaded through the retriever → reranker → compressor → gate.

    Carries the collected `raw` material, the per-column cardinality `caps`, and
    the `resolved` provenance for the high-card columns the retriever resolved.
    """

    raw: RawContext
    caps: Dict[str, int]
    resolved: Dict[str, ResolvedValues] = field(default_factory=dict)


class ContextEngine:
    """Builds a `ContextBundle` for one turn. Resolver is injectable for tests."""

    def __init__(self, *, resolver_factory=build_resolver, distinct_registry=None) -> None:
        self._resolver_factory = resolver_factory
        # DB-distinct value source (years etc.). Injectable for tests; defaults
        # lazily to the process-wide registry so the module imports without a DB.
        self._distinct_registry = distinct_registry

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
        """Assemble the full context bundle for `flow` + `query`.

        Reads top-to-bottom as the pipeline legend above advertises: each stage is
        a named method, and the reserved reranker/compressor seams are visible
        identity steps rather than missing links.
        """
        raw = self.collect_raw_context(flow, query, scopes=scopes, **collect_overrides)
        resolved = self.resolve_entities(flow, raw, query, resolver=resolver)  # retriever
        ranked = self.rank_candidates(resolved, query)        # reranker  (identity v1)
        selected = self.compress(ranked)                      # compressor (identity v1)
        gated = self.gate_valid_values(selected, query)       # cardinality gate
        # Source valid years from the DATA (not the hardcoded config lists) when
        # the caller doesn't supply them, so every bundle consumer — planner, SQL
        # agent, the timeframe resolver — reads live periods.
        if valid_year_quarter is None:
            valid_year_quarter = self.resolve_valid_years(flow)
        return self.assemble_bundle(
            selected,
            gated,
            routing_context=routing_context,
            valid_year_quarter=valid_year_quarter,
        )

    # --- stages -------------------------------------------------------------- #

    def collect_raw_context(
        self, flow: str, query: str, *, scopes: Sequence[str], **collect_overrides: Any
    ) -> RawContext:
        """COLLECTOR: gather the unfiltered schema / definitions / values / skills."""
        return collect(flow, query, scopes=scopes, **collect_overrides)

    def resolve_entities(
        self,
        flow: str,
        raw: RawContext,
        query: str,
        *,
        resolver: Optional[EntityResolver] = None,
    ) -> _ResolvedContext:
        """RETRIEVER: resolve each high-card column (fuzzy-first, LLM-rescue)."""
        caps = self._card_caps(flow, raw.full_valid_values)
        resolver = resolver or self._resolver_factory(flow)
        resolved = resolve_high_card(
            raw.full_valid_values, query, card_caps=caps, resolver=resolver
        )
        return _ResolvedContext(raw=raw, caps=caps, resolved=resolved)

    def rank_candidates(self, resolved: _ResolvedContext, query: str) -> _ResolvedContext:
        """RERANKER (identity in v1): deterministic ordering seam, no reordering yet."""
        return resolved

    def compress(self, ranked: _ResolvedContext) -> _ResolvedContext:
        """COMPRESSOR (identity in v1): extractive-selection seam, no trimming yet."""
        return ranked

    def resolve_valid_years(self, flow: str) -> list:
        """VALUES: data-sourced distinct years for the flow (ascending, latest last).

        Reads the DB via the `DistinctValueRegistry` rather than the hardcoded
        config lists. Degrades to [] on any error so value-sourcing can never
        break the bundle build.
        """
        registry = self._distinct_registry
        if registry is None:
            from core.registry.values import get_distinct_registry  # lazy: avoid DB import

            registry = get_distinct_registry()
        try:
            return registry.valid_years(flow)
        except Exception as exc:  # noqa: BLE001 - never let value-sourcing break the build
            logger.debug("resolve_valid_years(%s) failed: %s", flow, exc)
            return []

    def gate_valid_values(
        self, selected: _ResolvedContext, query: str
    ) -> Dict[str, list]:
        """GATE: low-card columns in full, high-card collapsed to resolved/sample."""
        return gate_with_resolved(
            selected.raw.full_valid_values,
            card_caps=selected.caps,
            resolved=selected.resolved,
        )

    def assemble_bundle(
        self,
        selected: _ResolvedContext,
        gated: Dict[str, list],
        *,
        routing_context: Any = None,
        valid_year_quarter: Optional[Sequence[str]] = None,
    ) -> ContextBundle:
        """BUNDLE: pack the gated values + provenance into the typed bundle."""
        raw = selected.raw
        return ContextBundle(
            flow=raw.flow,
            query=raw.query,
            schema_tables=raw.schema_tables,
            definitions=raw.definitions,
            valid_values=gated,
            resolved_entities=selected.resolved,
            skills=raw.skills,
            valid_year_quarter=list(valid_year_quarter or []),
            routing_context=routing_context,
        )

    # --- helpers ------------------------------------------------------------- #

    @staticmethod
    def _card_caps(flow: str, full_valid_values: Dict[str, Any]) -> Dict[str, int]:
        """Per-column cardinality caps from the registry (empty if no spec)."""
        spec = get_flow_registry().get(flow)
        if spec is None:
            return {}
        return {col: spec.card_cap(col) for col in full_valid_values}
