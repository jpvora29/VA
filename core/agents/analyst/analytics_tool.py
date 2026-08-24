"""`compute_metric` — the analytics library as one tool on the analyst solver.

The solver's `run_sql` asks the model to write the query. For the metrics whose
definition the business already signed off — rank, share of wallet, appetite, YoY,
peer average, NPS, whitespace — that is re-deriving a known recipe under time
pressure. This tool lets the solver ask for the metric BY NAME instead: arguments
are grounded against the flow registry and the number is computed by the same
tested primitive the deterministic rails use.

It is additive. `run_sql` stays exactly as it was and remains the right tool for
everything the library does not cover, so the solver loses no reach.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from core.analytics.orchestrator import AnalyticsOrchestrator
from core.analytics.tools import (
    ValueMatcher,
    catalog_text,
    facts_to_rows,
    ground_calls,
    tool_names,
)
from core.observability import log_event
from logger import get_logger

logger = get_logger(__name__)

# Rows echoed back to the model; the full set still lands in `evidence`.
ROW_PREVIEW = 25


class ComputeMetricArgs(BaseModel):
    """Arguments for `compute_metric` — the same shape a primitive takes."""

    flow: str = Field(description='Table family: "gpr" (premium) or "survey" (perception).')
    name: str = Field(description="The calculation to run, by name from the list below.")
    metric: str = Field(
        default="", description="Measure to compute over; omit for the flow's default."
    )
    group_by: List[str] = Field(
        default_factory=list,
        description="Dimension column(s) to cut by, e.g. ['Product_Line']. Empty for one total.",
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Filters as {column: value}, e.g. {'Carrier_Group': 'ZURICH GROUP', "
            "'Country': 'Canada', 'Year': 2024}. Unlike run_sql there is no implicit "
            "scope here — pass every filter the sub-question needs."
        ),
    )


def _description() -> str:
    """Tool description: what it does, plus the per-flow menu of calculations."""
    return (
        "Compute a signed-off insurance metric with a tested function instead of "
        "writing SQL. PREFER THIS over run_sql whenever one of the calculations "
        "below answers the sub-question: the definition is fixed, the value is "
        "reproducible, and filter values are matched to exact stored values for "
        "you. Returns JSON {row_count, rows}. Use run_sql for anything not listed.\n\n"
        f"GPR (premium) calculations:\n{catalog_text('gpr')}\n\n"
        f"Survey (perception) calculations:\n{catalog_text('survey')}"
    )


def build_compute_tool(
    evidence: List[Dict[str, Any]],
    lens: str,
    *,
    flow: str = "",
    peers: Sequence[str] = (),
    orchestrator: Optional[AnalyticsOrchestrator] = None,
    matcher: Optional[ValueMatcher] = None,
    engine: Optional[Any] = None,
):
    """A LangChain tool that computes a named metric and records it as evidence.

    `evidence` is the solver's own list (the same one `run_sql` appends to), so a
    computed result reaches the insight writer and the chart picker through the
    existing contract — no new plumbing downstream. `peers` pins the session's
    custom peer set for the solver's own flow; a call against another flow resolves
    peers from the `Peers` table as usual.
    """
    from langchain_core.tools import StructuredTool

    runner = orchestrator or AnalyticsOrchestrator()
    pinned_flow = flow

    def compute_metric(
        flow: str,
        name: str,
        metric: str = "",
        group_by: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> str:
        call = {
            "name": name,
            "metric": metric,
            "group_by": group_by or [],
            "filters": filters or {},
        }
        grounding = ground_calls(flow, [call], matcher=matcher, engine=engine)
        if not grounding.calls:
            reason = grounding.rejected[0].reason if grounding.rejected else "unknown"
            return (
                f"ERROR: cannot compute {name!r} for flow {flow!r} — {reason}. "
                f"Available: {list(tool_names(flow))}. Fix the arguments, or use "
                f"run_sql if no calculation covers this."
            )

        grounded = grounding.calls[0]
        # A pinned peer set belongs to one flow; a call against the other flow
        # resolves its peers from the Peers table as usual.
        pinned = tuple(peers) if peers and flow == pinned_flow else None
        result = runner.run(
            [
                {
                    "name": grounded.name,
                    "metric": grounded.metric,
                    "group_by": list(grounded.group_by),
                    "filters": dict(grounded.filters),
                    "options": dict(grounded.options),
                }
            ],
            flow=flow,
            engine=engine,
            subject=_subject(flow, grounded.filters),
            peers=pinned,
        )
        if result.skipped:
            return (
                f"ERROR: {name} could not be computed with those arguments. "
                f"Check the filters, or use run_sql."
            )

        rows = facts_to_rows(result.facts)
        provenance = f"-- computed: {grounded.describe()}"
        evidence.append({"flow": flow, "sql": provenance, "rows": rows, "lens": lens})
        log_event(
            logger,
            "compute_metric",
            node="analyst_solver",
            flow=flow,
            lens=lens,
            call=grounded.describe(),
            rows=len(rows),
        )
        return json.dumps(
            {"row_count": len(rows), "rows": rows[:ROW_PREVIEW]}, default=str
        )

    return StructuredTool.from_function(
        func=compute_metric,
        name="compute_metric",
        description=_description(),
        args_schema=ComputeMetricArgs,
    )


def _subject(flow: str, filters: Dict[str, Any]) -> Optional[str]:
    """The carrier being filtered on — the subject a peer comparison benchmarks."""
    from core.analytics.sql import flow_spec

    column = flow_spec(flow).entity_columns.get("carrier")
    value = filters.get(column) if column else None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value) if value else None
