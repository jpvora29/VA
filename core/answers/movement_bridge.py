"""Aligned quarterly rows for a chart, from the movement primitive.

A one-function seam so callers that want the quarterly comparison as CHART rows
(one column per year) do not each re-derive the year pair from the facts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping


def aligned_rows(scope: Mapping[str, Any], engine: Any = None) -> List[Dict[str, Any]]:
    """``[{Quarter, <prior year>, <current year>}]`` for `scope`, or []."""
    from core.analytics.movement import compute_aligned_periods
    from core.analytics.types import PrimitiveArgs
    from core.answers.chart_plan import quarterly_rows_from

    facts = compute_aligned_periods(
        PrimitiveArgs(flow="gpr", metric="premium", filters=dict(scope)), engine=engine
    )
    if not facts:
        return []
    dims = facts[0].dims
    return quarterly_rows_from(
        facts, current_year=int(dims.get("year")), prior_year=int(dims.get("prior_year"))
    )
