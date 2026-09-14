"""Proactive analysis layer: composable lenses + dynamic planner.

See `planner.py` for the lens library and `plan_analysis`, `lenses/*.md` for the
composable analytical moves, and `requirements.py` + `intents.yaml` for what
evidence a given analytical intent is entitled to be answered with.
"""
from core.analysis.planner import (
    LensLibrary,
    get_lens_library,
    plan_analysis,
)
from core.analysis.requirements import (
    EvidenceContract,
    Requirement,
    RequirementLibrary,
    UnmetRequirement,
    build_contract,
    get_requirements,
    performance_sources,
)

__all__ = [
    "LensLibrary",
    "get_lens_library",
    "plan_analysis",
    "EvidenceContract",
    "Requirement",
    "RequirementLibrary",
    "UnmetRequirement",
    "build_contract",
    "get_requirements",
    "performance_sources",
]
