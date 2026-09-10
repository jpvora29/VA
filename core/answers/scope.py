"""The displayed answer scope, shared with the UI rather than inferred from rows."""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from core.scope import CHIP_RULES, chips_from_state


DisplayScope = tuple[tuple[str, str], ...]


def answer_scope(state: Mapping) -> DisplayScope:
    return tuple((chip.key, chip.value) for chip in chips_from_state(state))


def scope_key(column: str) -> str:
    return next((key for key, _, _, pattern in CHIP_RULES if pattern.search(column)), column)


def matching_scope_dimensions(dimensions: list[dict[str, str]], scope: DisplayScope) -> set[tuple[str, str]]:
    """Hide a pill value only if that dimension does not vary in the evidence.

    Missing dimensions on a secondary result don't undo a known display filter.
    A country/product/period comparison still keeps its distinguishing labels.
    This only changes presentation; it never adds scope to a calculation.
    """
    observed = defaultdict(set)
    for dims in dimensions:
        for key, value in dims.items():
            observed[scope_key(key)].add(value.strip().casefold())
    shared = set()
    for kind, value in scope:
        if observed[kind] != {value.strip().casefold()}:
            continue
        shared.update((key, actual) for dims in dimensions for key, actual in dims.items()
                      if scope_key(key) == kind)
    return shared
