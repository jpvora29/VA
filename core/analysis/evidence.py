"""Lens → deterministic evidence bridge (Phase 3.5).

Turns a compound analytical request into facts. The analysis planner selects/orders
lenses (`plan_analysis`); each selected lens with a `primitives:` block contributes
deterministic primitive calls; this module runs them all through the analytics
orchestrator under the turn's shared scope (carrier + country + year) into a single
`EvidenceSet`. The narrative/SWOT synthesis then reads facts, inventing no numbers.

Lives in the analysis layer because it depends on BOTH the lens library and the
analytics orchestrator — keeping `core/analytics` free of any analysis import.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from core.analysis.planner import LensLibrary, get_lens_library
from core.analytics.orchestrator import AnalyticsOrchestrator, EvidenceSet


def collect_evidence(
    lens_names: Sequence[str],
    *,
    flow: str,
    scope: Optional[Mapping[str, Any]] = None,
    engine: Any = None,
    library: Optional[LensLibrary] = None,
    orchestrator: Optional[AnalyticsOrchestrator] = None,
) -> EvidenceSet:
    """Run the primitive bundles of the named lenses into one `EvidenceSet`.

    `scope` is the turn's shared filters applied to every call. Lenses without a
    `primitives:` block contribute nothing (they stay prompt-only). Dedup + caching
    are handled by the orchestrator, so a primitive shared across lenses (e.g.
    market presence) is computed once.
    """
    library = library or get_lens_library()
    orchestrator = orchestrator or AnalyticsOrchestrator()
    calls = library.primitive_calls(lens_names)
    return orchestrator.run(calls, flow=flow, shared_filters=scope, engine=engine)


def evidence_for_plan(
    analysis_plan: Any,
    *,
    flow: str,
    scope: Optional[Mapping[str, Any]] = None,
    engine: Any = None,
    library: Optional[LensLibrary] = None,
    orchestrator: Optional[AnalyticsOrchestrator] = None,
) -> EvidenceSet:
    """`collect_evidence` for the lenses an `AnalysisPlan` selected (`derived[].lens`)."""
    names = [
        d.lens
        for d in getattr(analysis_plan, "derived", []) or []
        if getattr(d, "lens", None)
    ]
    return collect_evidence(
        names, flow=flow, scope=scope, engine=engine, library=library, orchestrator=orchestrator
    )
