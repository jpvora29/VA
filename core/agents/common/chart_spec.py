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
