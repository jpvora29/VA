"""Cardinality-gated valid_values injection (decisions doc #2, step 3).

The headline token fix: the planner today receives the FULL `valid_values` dict,
including high-cardinality columns like GPR `Carrier_Group` (~550 values). The
gate keeps low-cardinality columns in full (they're cheap and useful) but
replaces a high-cardinality column with only the values the query actually
resolves to — plus a tiny candidate sample as a fallback.

`gate_valid_values` is pure (values + caps + matcher in, gated dict out) so it is
unit-tested without a DB or LLM. `gated_valid_values` wires the real registry
caps and the fuzzy matcher, lazily, and is guarded by `gate_enabled()`:

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


def _live_matcher(flow: str) -> Matcher:
    """Wire the fuzzy resolver from the MCP tools layer (lazy import)."""

    def match(column: str, query: str) -> List[str]:
        from core.mcp.tools import match_column_values  # lazy: pulls LLM layer

        return match_column_values(flow, column, query)

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
