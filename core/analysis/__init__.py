"""Proactive analysis layer: composable lenses + dynamic planner.

See `planner.py` for the lens library and `plan_analysis`, and `lenses/*.md`
for the composable analytical moves.
"""
from core.analysis.planner import (
    LensLibrary,
    get_lens_library,
    plan_analysis,
)

__all__ = ["LensLibrary", "get_lens_library", "plan_analysis"]
