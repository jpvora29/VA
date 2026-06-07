"""Normalize a chart node's dspy output into a single plain-dict spec.

Both chart nodes (`GPRChartNode` / `SurveyChartNode`) declare a single
`ChartOutput` OutputField, but dspy does not strictly enforce that: depending on
the model and adapter the parsed value can arrive as the pydantic model, a plain
dict, or — when the LLM emits more than one chart — a *list* of either. Every
downstream consumer (the analyst `pick_charts`, the deterministic chart stores,
and `ui.chart_functions._as_dict`) expects ONE dict. A stray list slips through
untouched and is then silently dropped, so the UI falls back to
"Chart can not be generated as the data is scalar."

`normalize_chart_spec` is the single coercion point: it unwraps a list to its
first usable element and flattens a model to a dict, returning `{}` when there is
nothing chartable.
"""
from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel


def normalize_chart_spec(chart_data: Any) -> Dict[str, Any]:
    """Coerce a chart OutputField (model, dict, or list of either) to one dict.

    The chart-node contract is one spec per call, so a list is unwrapped to its
    first non-empty element rather than merged. Returns `{}` when nothing usable
    is present, so callers can treat a missing/empty spec uniformly.
    """
    if isinstance(chart_data, (list, tuple)):
        chart_data = next((c for c in chart_data if c), None)

    if chart_data is None:
        return {}
    if isinstance(chart_data, BaseModel):
        return chart_data.model_dump()
    if isinstance(chart_data, dict):
        return dict(chart_data)
    return {}


# Cap on the user query we persist into the spec. The renderer only uses it for
# substring trend-term matching, so a generous prefix is plenty and keeps the
# stored message small.
_MAX_INTENT_LEN = 400


def stamp_intent(spec: Dict[str, Any], user_query: str) -> Dict[str, Any]:
    """Persist the user's question into the spec so the renderer can reason about
    intent at draw time.

    The chart renderer (`ui.chart_functions`) runs a deterministic guard that
    needs to know whether the user actually asked for a trend (→ keep `line`) or a
    comparison (→ force `bar`), and that decision must survive re-rendering of a
    stored message and Boardroom layout — neither of which has the original query
    in scope. Carrying it on the spec (rather than threading a new argument
    through every call site) makes the signal travel with the data it describes.

    Mutates and returns `spec`. A missing/blank query is left unstamped so legacy
    and override specs degrade to the title-only heuristic.
    """
    if not isinstance(spec, dict):
        return spec
    text = (user_query or "").strip()
    if text and not spec.get("intent"):
        spec["intent"] = text[:_MAX_INTENT_LEN]
    return spec
