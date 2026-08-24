"""Retriever layer — value resolution for the ContextEngine (decisions #4).

This is the layer that turns a high-cardinality column + a user query into the
*specific* values to inject. It is the **hybrid** seam:

  1. **Fuzzy (deterministic, default, zero model calls)** — `rapidfuzz` over the
     candidate values. Perfect for named entities: "Swiss Re" -> "SWISS RE".
  2. **Semantic (LLM-rescue, opt-in)** — fires ONLY when (a) fuzzy resolved
     nothing, (b) the column is flagged `resolver: semantic` in the registry
     (SIC major/minor, industry, product/cover/business line, segment,
     attributes), and (c) `CONTEXT_ENGINE_SEMANTIC` is on. A query like
     "manufacturing companies" shares no *string* with "Manufacture of motor
     vehicles", so string-distance can't bridge it — the LLM maps the concept to
     the real distinct values instead.

Fuzzy-first / LLM-rescue keeps v1's cost profile: the common path (named
entities, low-card columns) never touches the LLM. The model is paid for only
when deterministic matching demonstrably fails on a semantically rich column.

`EntityResolver` is pure given its injected callables — the fuzzy matcher, the
optional semantic matcher, and the `is_semantic` predicate are all passed in, so
it unit-tests without a DB or LLM. `build_resolver(flow)` wires the production
callables (lazily, so importing this module needs no credentials). The
embeddings / model-rerank retrieval interfaces from the decisions doc stay
stubbed (`SemanticIndex`) — built nothing now, per decision #12.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, List, Optional

from logger import get_logger

logger = get_logger(__name__)

# (column, query) -> resolved values. Same shape for fuzzy and semantic so they
# are interchangeable behind the resolver.
Matcher = Callable[[str, str], List[str]]
Predicate = Callable[[str], bool]


def semantic_enabled() -> bool:
    """True when the LLM-rescue resolver may fire (default off)."""
    return os.getenv("CONTEXT_ENGINE_SEMANTIC", "off").lower() in {"on", "shadow"}


@dataclass(frozen=True)
class ResolvedValues:
    """The values a column resolved to, plus which strategy produced them."""

    column: str
    values: List[str]
    source: str  # "fuzzy" | "semantic" | "none"

    def __bool__(self) -> bool:
        return bool(self.values)


@dataclass
class EntityResolver:
    """Fuzzy-first, LLM-rescue value resolution for a single flow.

    Args:
        fuzzy: deterministic matcher; always tried first.
        is_semantic: predicate marking a column as LLM-rescue eligible.
        semantic: optional LLM matcher; only invoked on a semantic column after
            fuzzy misses, and only when `enabled`.
        enabled: gate for the semantic rescue (reads `CONTEXT_ENGINE_SEMANTIC`).
    """

    fuzzy: Matcher
    is_semantic: Predicate = lambda _col: False
    semantic: Optional[Matcher] = None
    enabled: bool = False

    def resolve(self, column: str, query: str) -> ResolvedValues:
        matches = self.fuzzy(column, query) or []
        if matches:
            return ResolvedValues(column, list(matches), "fuzzy")

        if self.enabled and self.semantic is not None and self.is_semantic(column):
            try:
                semantic = self.semantic(column, query) or []
            except Exception as exc:  # noqa: BLE001 - rescue must never break the gate
                logger.debug("semantic resolve(%s) failed: %s", column, exc)
                semantic = []
            if semantic:
                logger.debug("semantic-rescued %s -> %d value(s)", column, len(semantic))
                return ResolvedValues(column, list(semantic), "semantic")

        return ResolvedValues(column, [], "none")

    def match(self, column: str, query: str) -> List[str]:
        """Adapter to the plain `(column, query) -> List[str]` Matcher contract.

        Lets an `EntityResolver` drop straight into the step-3 cardinality gate
        (`gate_valid_values`'s `matcher=`) so the hybrid benefits every call site
        already wired to the gate, with no signature change.
        """
        return self.resolve(column, query).values


# --------------------------------------------------------------------------- #
# Production wiring (lazy — importing this module pulls no DB / LLM).
# --------------------------------------------------------------------------- #


def _fuzzy_matcher(flow: str) -> Matcher:
    """The deterministic rapidfuzz resolver from the MCP tools layer."""

    def match(column: str, query: str) -> List[str]:
        from core.mcp.tools import match_column_values  # lazy

        return match_column_values(flow, column, query)

    return match


def llm_semantic_matcher(flow: str) -> Matcher:
    """LLM resolver: map a conceptual query to a semantic column's real values.

    Lazy and self-contained — built only when the rescue actually fires. Given
    the column's distinct candidate values + the query, the model returns the
    subset the query refers to (e.g. "manufacturing" -> the relevant SIC
    classes). Returns [] on any failure so the caller degrades to "no match".
    """

    def match(column: str, query: str) -> List[str]:
        from core.mcp.tools import _candidate_values  # lazy

        candidates = _candidate_values(flow, column)
        if not candidates:
            return []
        from core.context.semantic import resolve_semantic_values  # lazy: pulls the LLM layer

        return resolve_semantic_values(
            column=column, query=query, candidates=candidates
        )

    return match


def build_resolver(flow: str, *, enabled: Optional[bool] = None) -> EntityResolver:
    """Wire the production hybrid resolver for `flow`.

    Reads the `resolver: semantic` flags from the registry and the
    `CONTEXT_ENGINE_SEMANTIC` env gate (override with `enabled=` in tests).
    """
    from core.registry import get_flow_registry

    spec = get_flow_registry().get(flow)
    is_semantic = spec.is_semantic_column if spec is not None else (lambda _c: False)
    return EntityResolver(
        fuzzy=_fuzzy_matcher(flow),
        is_semantic=is_semantic,
        semantic=llm_semantic_matcher(flow),
        enabled=semantic_enabled() if enabled is None else enabled,
    )


# --------------------------------------------------------------------------- #
# Stubbed interfaces (decision #12 — build nothing now).
# --------------------------------------------------------------------------- #


class SemanticIndex:
    """Embeddings-backed retrieval seam. Interface only — NOT implemented in v1.

    Reserved so the engine can later add dense retrieval / model rerank without
    a structural change. Calling it is a deliberate failure, not a silent stub.
    """

    def search(self, query: str, top_k: int = 10) -> List[str]:  # pragma: no cover
        raise NotImplementedError(
            "Embeddings retrieval is out of scope for ContextEngine v1 "
            "(decisions doc #12 — interface seam only)."
        )
