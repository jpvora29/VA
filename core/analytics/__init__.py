"""Deterministic analytics library.

Pure-function primitives that compute the numbers the LLM used to invent. One
flow-agnostic registry serves both GPR (premium) and Survey (score/NPS). See
``core/deterministic_analytics_plan.md`` for the design and phase plan.

Public surface:

- Contracts: `AnalyticsFact`, `PrimitiveArgs`, `FactFrame`, `CompositePrimitive`.
- Frame building: `build_frame`, `detect_roles`.
- Dispatch: `AnalyticsRegistry`, `build_default_registry`.
"""
from __future__ import annotations

from core.analytics.frame import build_frame, detect_roles
from core.analytics.library import (
    compute_attribute_breakdown,
    compute_breakdown,
    compute_market_presence,
    compute_nps,
    compute_peer_average,
    compute_rank,
    compute_share_of_portfolio,
    compute_share_of_wallet,
    compute_yoy,
    compute_yoy_to_date,
    find_service_gaps,
    find_whitespace,
    get_latest_quarter,
    get_latest_year,
)
from core.analytics.library import LIBRARY
from core.analytics.orchestrator import AnalyticsOrchestrator, EvidenceSet
from core.analytics.primitives import BUILTINS
from core.analytics.registry import AnalyticsRegistry, UnknownPrimitiveError
from core.analytics.timeframe import (
    resolve_default_timeframe,
    timeframe_resolution_enabled,
)
from core.analytics.types import (
    AnalyticsFact,
    CompositePrimitive,
    FactFrame,
    PrimitiveArgs,
    PrimitiveFn,
)

__all__ = [
    "AnalyticsFact",
    "PrimitiveArgs",
    "FactFrame",
    "CompositePrimitive",
    "PrimitiveFn",
    "build_frame",
    "detect_roles",
    "AnalyticsRegistry",
    "UnknownPrimitiveError",
    "build_default_registry",
    "resolve_default_timeframe",
    "timeframe_resolution_enabled",
    "compute_breakdown",
    "compute_rank",
    "compute_yoy",
    "compute_yoy_to_date",
    "get_latest_year",
    "get_latest_quarter",
    "compute_share_of_portfolio",
    "compute_market_presence",
    "compute_peer_average",
    "compute_share_of_wallet",
    "compute_nps",
    "compute_attribute_breakdown",
    "find_whitespace",
    "find_service_gaps",
    "LIBRARY",
    "AnalyticsOrchestrator",
    "EvidenceSet",
]


def build_default_registry() -> AnalyticsRegistry:
    """Construct a registry populated with the built-in primitives.

    Explicit construction (no import-time global mutation) keeps wiring obvious
    and lets tests build isolated registries.
    """
    return AnalyticsRegistry(BUILTINS)
