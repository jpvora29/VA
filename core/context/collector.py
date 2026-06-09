"""Collector layer — gathers the raw context candidates for a turn.

First stage of the ContextEngine pipeline (collector -> retriever -> reranker ->
compressor -> injection). It pulls the *unfiltered* material from the existing
sources — schema slice, business definitions, full valid_values, and the skill
bodies triggered for each scope — and hands them on as a `RawContext`. No
trimming or model calls happen here; the gate (retriever/injection) and the
bundle views do the narrowing downstream.

Every source is injectable so the collector unit-tests with no DB / LLM / skills
on disk. In production the defaults read the flow registry and the live engine
lazily.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from logger import get_logger

logger = get_logger(__name__)

# Skill scopes the engine assembles per turn. Routing needs none (structure
# only); chart/pitch are pulled by their own nodes when those paths run.
DEFAULT_SCOPES: tuple[str, ...] = ("planner", "sql", "response")


@dataclass
class RawContext:
    """Unfiltered context material for one turn, before gating/views."""

    flow: str
    query: str
    schema_tables: Dict[str, Any] = field(default_factory=dict)
    definitions: Dict[str, str] = field(default_factory=dict)
    full_valid_values: Dict[str, Any] = field(default_factory=dict)
    skills: Dict[str, str] = field(default_factory=dict)  # scope -> rendered body


def _default_schema_provider(flow: str) -> Callable[[], Dict[str, Any]]:
    def provider() -> Dict[str, Any]:
        from core.mcp.tools import get_schema  # lazy: pulls data layer

        return get_schema(flow)

    return provider


def _default_valid_values_provider(flow: str) -> Callable[[], Dict[str, Any]]:
    def provider() -> Dict[str, Any]:
        from core.mcp.tools import get_valid_values  # lazy

        return get_valid_values(flow)

    return provider


def _default_definitions_provider(flow: str) -> Callable[[], Dict[str, str]]:
    def provider() -> Dict[str, str]:
        from core.mcp.tools import get_definitions  # lazy

        return get_definitions(flow)

    return provider


def _default_skill_provider(flow: str) -> Callable[[str, str], Optional[str]]:
    def provider(scope: str, query: str) -> Optional[str]:
        from core.skills.loader import get_skill_loader  # lazy

        return get_skill_loader().load(flow, scope, query)

    return provider


def collect(
    flow: str,
    query: str,
    *,
    scopes: Sequence[str] = DEFAULT_SCOPES,
    schema_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    valid_values_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    definitions_provider: Optional[Callable[[], Dict[str, str]]] = None,
    skill_provider: Optional[Callable[[str, str], Optional[str]]] = None,
) -> RawContext:
    """Gather raw context for `flow` + `query`. Sources are injectable for tests."""
    schema_provider = schema_provider or _default_schema_provider(flow)
    valid_values_provider = valid_values_provider or _default_valid_values_provider(flow)
    definitions_provider = definitions_provider or _default_definitions_provider(flow)
    skill_provider = skill_provider or _default_skill_provider(flow)

    skills: Dict[str, str] = {}
    for scope in scopes:
        try:
            body = skill_provider(scope, query)
        except Exception as exc:  # noqa: BLE001 - a bad skill must not break context
            logger.debug("skill load(%s/%s) failed: %s", flow, scope, exc)
            body = None
        if body:
            skills[scope] = body

    return RawContext(
        flow=flow,
        query=query,
        schema_tables=schema_provider() or {},
        definitions=definitions_provider() or {},
        full_valid_values=valid_values_provider() or {},
        skills=skills,
    )
