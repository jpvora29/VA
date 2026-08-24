"""Analytics primitives as callable tools.

The chatbot used to ask the model to WRITE the SQL for a metric whose recipe we
already own. This package turns that around: each primitive in
`core.analytics.library` is published as a tool the model may CALL, its arguments
are grounded against the flow registry, and the number itself is computed by the
tested function — never by the model.

Layers, each one testable on its own:

- `catalog`   — primitive -> tool descriptor + JSON schema (registry-derived enums).
- `grounding` — a selected call -> a runnable call, or a reasoned rejection.
- `scope`     — the turn's shared filters (contract + plan + timeframe), no LLM.
- `rows`      — computed facts -> the row dicts the charts/insight/UI already take.

Nothing here imports dspy, LangChain, or the graph: selection (the one LLM step)
lives in `core.agents.common.analytics_tools`.
"""
from __future__ import annotations

from core.analytics.tools.catalog import (
    CATALOG,
    ToolSpec,
    catalog_text,
    dimension_columns,
    metric_names,
    tool_catalog,
    tool_names,
    tool_schemas,
)
from core.analytics.tools.grounding import (
    FilterGrounding,
    GroundedCall,
    GroundingResult,
    RejectedCall,
    ValueMatcher,
    ground_call,
    ground_calls,
    ground_filters,
)
from core.analytics.tools.rows import column_label, facts_digest, facts_to_rows
from core.analytics.tools.scope import TurnScope, turn_scope, years_in

__all__ = [
    "CATALOG",
    "ToolSpec",
    "catalog_text",
    "dimension_columns",
    "metric_names",
    "tool_catalog",
    "tool_names",
    "tool_schemas",
    "FilterGrounding",
    "GroundedCall",
    "GroundingResult",
    "RejectedCall",
    "ValueMatcher",
    "ground_call",
    "ground_calls",
    "ground_filters",
    "column_label",
    "facts_digest",
    "facts_to_rows",
    "TurnScope",
    "turn_scope",
    "years_in",
]
