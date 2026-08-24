"""Normalize a chart node's output into a single plain-dict spec.

Both chart nodes (`GPRChartNode` / `SurveyChartNode`) declare a single
`ChartOutput` OutputField, but that is not strictly enforced: depending on
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

from typing import Any, Callable, Dict, List, Optional

from core.llm import InputField, OutputField, Signature
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


# ── two-phase chart generation (select → detail) ────────────────────────────
#
# The chart node used to receive ALL six per-type guidance blocks in one prompt
# and let the model both pick a type and map fields in a single pass. We now split
# it: a cheap phase-one predictor reads only the `chart-type-selection` decision
# tree and emits the `chart_type`; phase two then injects ONLY that type's detail
# (`SkillLoader.chart_detail`) for the field-mapping pass. Smaller prompts, and the
# model can't be distracted by five irrelevant chart guides.

# The chart_type enum the selector may emit (mirrors `ChartOutput.chart_type` and
# the chart-type-selection skill). `none` short-circuits — nothing to chart.
CHART_TYPES = frozenset(
    {"bar", "line", "pie", "donut", "scatter", "waterfall", "combo"}
)


class ChartTypeSelectSignature(Signature):
    """
    [ROLE]
    You are a data-visualization analyst. Decide ONLY the single best chart_type
    for the user's intent and the shape of the SQL output, using the chart type
    selection rules. Do not map fields or build a spec — return just the type.

    [OUTPUT]
    `chart_type` MUST be exactly one of: bar, line, pie, donut, scatter,
    waterfall, combo, none. Use `none` when the result is a single scalar or has
    no categorical/time column to put on an axis.
    """

    chart_type_rules: str = InputField(
        desc="The chart-type-selection decision tree (how to choose the type)."
    )
    user_query: str = InputField(desc="User's natural language question.")
    sql_output: List[Dict[str, Any]] = InputField(
        desc="SQL result rows (list of dicts) to be visualized."
    )
    chart_type: str = OutputField(
        desc="One of: bar, line, pie, donut, scatter, waterfall, combo, none."
    )


def sanitize_chart_type(value: Any) -> str:
    """Coerce a phase-one result to a known type, ``'none'``, or ``''``.

    Returns the lowercased enum value when valid, ``'none'`` when the model says
    there is nothing to chart, and ``''`` for junk/empty — the caller treats the
    empty case as "selector unusable" and falls back to a single-phase pass.
    """
    raw = getattr(value, "chart_type", value)
    text = str(raw or "").strip().lower()
    if text in CHART_TYPES:
        return text
    if text == "none":
        return "none"
    return ""


def generate_chart_two_phase(
    *,
    base_rules: str,
    user_query: str,
    sql_output: List[Dict[str, Any]],
    type_predictor: Callable[..., Any],
    spec_predictor: Callable[..., Any],
    detail_provider: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    """Run select→detail and return a single normalized chart spec dict.

    ``type_predictor`` and ``spec_predictor`` are predictors (or any callable
    matching their signatures, so this is unit-testable with stubs). On a concrete
    type, only that type's detail is appended to ``base_rules`` and the decided
    type is stamped onto the result. ``none`` returns ``{}`` (skip). If phase one
    is unusable (``''``), we fall back to a single-phase pass on ``base_rules``.
    """
    try:
        decided = sanitize_chart_type(
            type_predictor(
                chart_type_rules=base_rules,
                user_query=user_query,
                sql_output=sql_output,
            )
        )
    except Exception:  # noqa: BLE001 - selector must never crash charting
        decided = ""

    if decided == "none":
        return {}

    rules = base_rules
    detail = detail_provider(decided) if decided else None
    if detail:
        rules = f"{base_rules}\n\n{detail}"

    spec = normalize_chart_spec(
        spec_predictor(
            chart_creation_rules=rules,
            user_query=user_query,
            sql_output=sql_output,
        ).chart_data
    )
    if spec and decided:
        spec["chart_type"] = decided
    return spec
