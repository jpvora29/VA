"""Built-in analytics primitives.

Phase 0 ships one — `count_distinct_periods` — to prove the contract end-to-end:
a pure ``(frame, args) -> AnalyticsFact`` function that reads columns by role and
returns a deterministic, provenance-bearing fact. It is deliberately useful
beyond the demo: Phase 1 (timeframe resolution) and Phase 4 (timeline gating both
need a distinct-period count).

Later phases append the real library here (rank, share-of-portfolio, peer-average,
yoy, find_whitespace, …); `BUILTINS` is the dictionary the default registry is
built from.
"""
from __future__ import annotations

import re
from typing import Dict

from core.analytics.types import AnalyticsFact, FactFrame, PrimitiveArgs, PrimitiveFn

_YEAR_COL = re.compile(r"(?i)year")


def count_distinct_periods(frame: FactFrame, args: PrimitiveArgs) -> AnalyticsFact:
    """Count distinct time periods present in the data.

    Prefers a year-like temporal column (the unit timeline gating cares about);
    falls back to the first temporal column otherwise. Returns 0 cleanly when the
    result set carries no temporal column.
    """
    temporal = frame.columns("temporal")
    year_cols = [c for c in temporal if _YEAR_COL.search(str(c))]
    target = (year_cols or list(temporal))[:1]
    column = target[0] if target else ""

    values: set = set()
    for col in target:
        for row in frame.rows:
            val = row.get(col)
            if val not in (None, ""):
                values.add(str(val).strip())

    count = len(values)
    return AnalyticsFact(
        name="distinct_periods",
        value=count,
        unit="count",
        rendered=str(count),
        dims={"column": column},
        support=[{column: v} for v in sorted(values)] if column else [],
        formula=f"COUNT(DISTINCT {column or 'period'})",
    )


# The dictionary the default registry is built from. Append new primitives here.
BUILTINS: Dict[str, PrimitiveFn] = {
    "count_distinct_periods": count_distinct_periods,
}
