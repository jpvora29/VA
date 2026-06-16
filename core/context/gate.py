"""Cardinality-gated valid_values gate (decisions doc #2, step 3).

> Renamed from `injection.py` in Phase 0. This module is the **valid-values
> cardinality gate**, not a context injector — the genuinely-named
> `ContextInjector` (node → per-audience view) lives in `core/context/injector.py`.

The headline token fix: the planner today receives the FULL `valid_values` dict,
including high-cardinality columns like GPR `Carrier_Group` (~550 values). The
gate keeps low-cardinality columns in full (they're cheap and useful) but
replaces a high-cardinality column with only the values the query actually
resolves to — plus a tiny candidate sample as a fallback.

The two halves are kept as separate pure functions (SRP) so the engine can show
them as distinct pipeline stages:

  - `resolve_high_card`  — RETRIEVER: resolve each high-card column to its values.
  - `gate_with_resolved` — GATE: low-card → full list; high-card → resolved/sample.

`gate_valid_values` is the pure one-shot form (values + caps + matcher in, gated
dict out) used directly by the production `gated_valid_values` entry point and
unit-tested without a DB or LLM. It is guarded by `gate_enabled()`:

  CONTEXT_ENGINE_VALID_VALUES = off (default) | shadow | on

Default off = zero behavior change. Flip to `on` (with a live run + the golden
harness) before relying on the token savings.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from core.registry.loader import get_flow_registry
from core.registry.spec import DEFAULT_CARD_CAP

# Fallback candidate count for a high-card column when the query resolves nothing.
HIGH_CARD_SAMPLE = 5

Matcher = Callable[[str, str], List[str]]  # (column, query) -> resolved values


def gate_enabled() -> bool:
    """True when the planner should receive gated (not full) valid_values."""
    return os.getenv("CONTEXT_ENGINE_VALID_VALUES", "off").lower() in {"on", "shadow"}


def is_high_card(values: Any, *, cap: int) -> bool:
    """True when a column's distinct count exceeds its cap (needs resolution)."""
    return values is not None and len(list(values)) > cap


def gate_valid_values(
    full_values: Dict[str, Any],
    query: str,
    *,
    card_caps: Dict[str, int],
    matcher: Matcher,
    sample_size: int = HIGH_CARD_SAMPLE,
) -> Dict[str, List[str]]:
    """Return a token-reduced copy of `full_values`.

    Per column:
      - distinct count <= cap  -> keep the full list (low-card, cheap).
      - otherwise (high-card)  -> the query-resolved matches; if none resolve,
        a small candidate sample so the planner still sees the column's shape.
    """
    gated: Dict[str, List[str]] = {}
    for column, values in full_values.items():
        if values is None:
            continue
        values_list = list(values)
        cap = card_caps.get(column, DEFAULT_CARD_CAP)
        if len(values_list) <= cap:
            gated[column] = values_list
            continue
        matches = matcher(column, query) or []
        gated[column] = matches if matches else values_list[:sample_size]
    return gated


def resolve_high_card(
    full_values: Dict[str, Any],
    query: str,
    *,
    card_caps: Dict[str, int],
    resolver: "EntityResolver",
    default_cap: int = DEFAULT_CARD_CAP,
) -> Dict[str, "ResolvedValues"]:
    """RETRIEVER stage: resolve every HIGH-card column to its `ResolvedValues`.

    Low-card columns are skipped (they pass through the gate in full and need no
    resolution). The returned map carries the per-column resolution provenance
    (values + source) the solver view / observability reads.
    """
    resolved: Dict[str, ResolvedValues] = {}
    for column, values in full_values.items():
        cap = card_caps.get(column, default_cap)
        if not is_high_card(values, cap=cap):
            continue
        resolved[column] = resolver.resolve(column, query)
    return resolved


def gate_with_resolved(
    full_values: Dict[str, Any],
    *,
    card_caps: Dict[str, int],
    resolved: Dict[str, "ResolvedValues"],
    sample_size: int = HIGH_CARD_SAMPLE,
    default_cap: int = DEFAULT_CARD_CAP,
) -> Dict[str, List[str]]:
    """GATE stage: assemble the gated dict from full values + the resolved map.

    Low-card columns keep their full list; high-card columns take their resolved
    values, falling back to a small candidate sample when nothing resolved.
    """
    gated: Dict[str, List[str]] = {}
    for column, values in full_values.items():
        if values is None:
            continue
        values_list = list(values)
        cap = card_caps.get(column, default_cap)
        if len(values_list) <= cap:
            gated[column] = values_list
            continue
        rv = resolved.get(column)
        gated[column] = rv.values if (rv and rv.values) else values_list[:sample_size]
    return gated


def assemble_valid_values(
    full_values: Dict[str, Any],
    query: str,
    *,
    card_caps: Dict[str, int],
    resolver: "EntityResolver",
    sample_size: int = HIGH_CARD_SAMPLE,
):
    """Gate values AND record per-column resolution provenance.

    Composes the two stages: `resolve_high_card` (retriever) then
    `gate_with_resolved` (gate). Returns `(gated, resolved)` where `resolved`
    maps each high-card column to its `ResolvedValues` (values + source). The
    ContextEngine uses `gated` for prompts and `resolved` for the solver view /
    observability.
    """
    resolved = resolve_high_card(
        full_values, query, card_caps=card_caps, resolver=resolver
    )
    gated = gate_with_resolved(
        full_values, card_caps=card_caps, resolved=resolved, sample_size=sample_size
    )
    return gated, resolved


def _live_matcher(flow: str) -> Matcher:
    """Wire the hybrid resolver for the gate's high-card matching (lazy import).

    Fuzzy-first, LLM-rescue (decision #4): the deterministic rapidfuzz matcher is
    always tried first; for a registry `resolver: semantic` column, a fuzzy miss
    escalates to the LLM resolver when `CONTEXT_ENGINE_SEMANTIC` is on. This makes
    every gate call site (planner, SQL agent) hybrid-capable with no change there.
    """

    def match(column: str, query: str) -> List[str]:
        from core.context.retriever import build_resolver  # lazy: pulls LLM layer

        return build_resolver(flow).match(column, query)

    return match


def gated_valid_values(
    flow: str, query: str, *, full_values: Optional[Dict[str, Any]] = None
) -> Dict[str, List[str]]:
    """Production entry point: gate this flow's valid_values for `query`.

    `full_values` may be passed (the caller already has it); otherwise it is read
    from the registry. Caps come from the registry's per-column `card_cap`.
    """
    registry = get_flow_registry()
    spec = registry.get(flow) or registry.get("survey")
    values = full_values if full_values is not None else spec.valid_values()
    caps = {col: spec.card_cap(col) for col in values}
    return gate_valid_values(values, query, card_caps=caps, matcher=_live_matcher(flow))
