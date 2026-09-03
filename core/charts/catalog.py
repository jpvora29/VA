"""Each chart type, described as its OWN tool with its OWN argument schema.

The chart model has always been handed one fat `ChartOutput` schema carrying every
field any chart type might need — `bar_mode` for bars, `secondary_y` for combos,
`waterfall_measures` for waterfalls — and asked, in prose, to fill only the
relevant ones. That is a schema which permits nonsense: a pie with a `bar_mode`, a
scatter with a `series`, a combo whose rate column sits in `y` next to an amount.
`ChartSpecCritic` then repairs the wreckage after the fact.

This module inverts that. One tool per chart type, each declaring ONLY the
arguments that type can legitimately take, with the column enums drawn from the
result set the chart will actually be drawn from — and narrowed by column ROLE, so

  * `y` offers measures only (a categorical in y is not expressible),
  * `series` offers dimensions small enough to be a readable legend,
  * a scatter's `x` offers measures, while a line's `x` offers temporal columns,
  * `secondary_y` offers rate-like measures only.

A hallucinated column, a categorical measure, and a 15-entry legend all stop being
possible before the model speaks, rather than being corrected afterwards. The
critic stays exactly where it is — prevention narrows, the critic still catches.

Pure and dependency-light: pandas + `core.charts.profile` only, no LLM layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.charts.profile import ColumnProfile

# A legend longer than this is unreadable, so a column with more distinct values
# is never offered as `series`. Mirrors `critic.MAX_LEGEND_ENTRIES` — the critic
# enforces the same ceiling after the fact for specs that bypass this path.
MAX_SERIES_CARDINALITY = 8

# Above this many slices a part-to-whole chart stops communicating, so pie/donut
# are simply not offered for a wider result. Mirrors `critic.MAX_PIE_SLICES`.
MAX_PIE_SLICES = 8


@dataclass(frozen=True)
class ChartToolSpec:
    """One chart type, described for tool selection.

    `requires` is a business guardrail rather than bookkeeping: offering `line`
    when the data has no temporal column, or `waterfall` when there is nothing to
    bridge, invites a chart that cannot be drawn. A type whose requirements the
    result set does not meet is not offered at all, so it cannot be chosen.
    """

    name: str
    summary: str
    use_when: str
    # Column-role kinds that must be present in the result for this type to apply.
    requires: Tuple[str, ...] = ()
    # Argument builders this type declares, in prompt order.
    arguments: Tuple[str, ...] = ()

    @property
    def tool_name(self) -> str:
        return f"draw_{self.name}"


_SPECS: Tuple[ChartToolSpec, ...] = (
    ChartToolSpec(
        name="bar",
        summary="Compare one or more measures across discrete categories.",
        use_when=(
            "categories are compared for a single period, or one measure is split "
            "by a second category. This is the default when nothing else fits."
        ),
        requires=("dimension_or_temporal", "measure"),
        arguments=("x_category", "y_measures", "series", "bar_mode", "sort", "title"),
    ),
    ChartToolSpec(
        name="line",
        summary="Show a measure moving over time.",
        use_when=(
            "the question is about a trend, trajectory, or movement across "
            "periods AND the result carries at least two distinct periods. A "
            "multi-year comparison across categories is a grouped bar, not a line."
        ),
        requires=("temporal", "measure"),
        arguments=("x_temporal", "y_measures", "series", "title"),
    ),
    ChartToolSpec(
        name="donut",
        summary="Show parts of a whole as a ring (preferred over pie).",
        use_when=(
            "components sum to a meaningful 100% and there are few enough slices "
            "to read — portfolio mix, appetite split, score by section."
        ),
        requires=("dimension", "measure", "few_categories"),
        arguments=("labels", "values", "title"),
    ),
    ChartToolSpec(
        name="pie",
        summary="Show parts of a whole as a pie.",
        use_when=(
            "the same case as donut and the user explicitly asked for a pie. "
            "Otherwise prefer donut."
        ),
        requires=("dimension", "measure", "few_categories"),
        arguments=("labels", "values", "title"),
    ),
    ChartToolSpec(
        name="scatter",
        summary="Show the relationship between TWO numeric measures, one per axis.",
        use_when=(
            "the question is about correlation between two measures (SoW% vs "
            "growth, score vs NPS). Never use it to put time on an axis."
        ),
        requires=("two_measures",),
        arguments=("x_measure", "y_measure", "series", "title"),
    ),
    ChartToolSpec(
        name="waterfall",
        summary="Bridge an opening value to a closing value through signed steps.",
        use_when=(
            "the question is about what DROVE a change — a premium walk from "
            "opening through new business / rate / churn to closing."
        ),
        requires=("dimension_or_temporal", "measure"),
        arguments=("x_steps", "y_measure", "step_kinds", "title"),
    ),
    ChartToolSpec(
        name="combo",
        summary="Bars for an absolute amount plus a line for a rate on a second axis.",
        use_when=(
            "two measures of DIFFERENT units must be read together — premium "
            "bars with growth% or share-of-wallet% as a line. Never put an "
            "amount and a rate on the same axis."
        ),
        requires=("dimension_or_temporal", "amount_and_rate"),
        arguments=("x_category", "y_amounts", "secondary_y_rates", "title"),
    ),
)

CATALOG: Dict[str, ChartToolSpec] = {spec.name: spec for spec in _SPECS}


# ── which types this result set can actually support ─────────────────────────


def _meets(requirement: str, profile: ColumnProfile) -> bool:
    """True when the result set satisfies one of a chart type's requirements."""
    checks = {
        "temporal": lambda: bool(profile.temporal),
        "dimension": lambda: bool(profile.dimensions),
        "measure": lambda: bool(profile.measures),
        "dimension_or_temporal": lambda: bool(profile.dimensions or profile.temporal),
        "two_measures": lambda: len(profile.measures) >= 2,
        "amount_and_rate": lambda: bool(profile.amounts and profile.rates),
        "few_categories": lambda: any(
            profile.cardinality(col) <= MAX_PIE_SLICES for col in profile.dimensions
        ),
    }
    check = checks.get(requirement)
    return bool(check and check())


def applicable_types(profile: ColumnProfile) -> Tuple[ChartToolSpec, ...]:
    """The chart types this result set can legitimately support, in catalog order.

    A type whose requirements the data does not meet is withheld rather than
    offered-and-rejected: the cheapest way to stop a line chart with no time axis
    is to make it unselectable.
    """
    return tuple(
        spec
        for spec in CATALOG.values()
        if all(_meets(req, profile) for req in spec.requires)
    )


# ── argument schemas, with enums drawn from the real columns ─────────────────


def _enum(
    columns: List[str], description: str, *, multiple: bool = False
) -> Dict[str, Any]:
    """One argument: a closed list of real column names, single or multi-valued."""
    item = {"type": "string", "enum": list(columns)}
    if multiple:
        return {"type": "array", "items": item, "description": description}
    return {**item, "description": description}


def _argument(name: str, profile: ColumnProfile) -> Optional[Dict[str, Any]]:
    """The JSON-schema fragment for one named argument, or None when unavailable."""
    axis_columns = profile.dimensions + profile.temporal
    legend_columns = [
        col
        for col in profile.dimensions
        if 1 < profile.cardinality(col) <= MAX_SERIES_CARDINALITY
    ]
    builders: Dict[str, Any] = {
        "x_category": lambda: _enum(
            axis_columns, "The category or period on the X axis."
        ),
        "x_temporal": lambda: _enum(
            profile.temporal, "The time column on the X axis."
        ),
        "x_measure": lambda: _enum(
            profile.measures, "The measure on the X axis."
        ),
        "x_steps": lambda: _enum(
            axis_columns, "The column naming each step of the bridge, in order."
        ),
        "labels": lambda: _enum(
            [col for col in profile.dimensions if profile.cardinality(col) <= MAX_PIE_SLICES],
            "The column whose values name the slices.",
        ),
        "values": lambda: _enum(profile.measures, "The measure each slice sizes by."),
        "y_measures": lambda: _enum(
            profile.measures,
            "The measure column(s) on the Y axis. Same unit only — mixing an "
            "amount with a rate needs draw_combo instead.",
            multiple=True,
        ),
        "y_measure": lambda: _enum(profile.measures, "The measure on the Y axis."),
        "y_amounts": lambda: _enum(
            profile.amounts or profile.measures,
            "The absolute measure(s) drawn as BARS on the primary axis.",
            multiple=True,
        ),
        "secondary_y_rates": lambda: _enum(
            profile.rates,
            "The rate/percentage measure(s) drawn as a LINE on the right-hand axis.",
            multiple=True,
        ),
        "series": lambda: _enum(
            legend_columns,
            "Optional column whose values become the colour legend. Omit for a "
            "single series — a legend is only worth its space when it separates "
            "things the reader must compare.",
            multiple=True,
        ),
        "bar_mode": lambda: {
            "type": "string",
            "enum": ["group", "stack"],
            "description": (
                "'stack' when the series parts SUM to the category total (a "
                "component mix); 'group' when they are independent comparisons "
                "side by side. Only meaningful with a series."
            ),
        },
        "sort": lambda: {
            "type": "string",
            "enum": ["desc", "asc", "none"],
            "description": (
                "'desc' for a ranking or top-N question; 'none' keeps the data's "
                "own order (use it when X is a period)."
            ),
        },
        "step_kinds": lambda: {
            "type": "array",
            "items": {"type": "string", "enum": ["relative", "total"]},
            "description": (
                "One entry per step, in order: 'relative' for a +/- movement, "
                "'total' for an absolute subtotal bar. Omit to treat every step "
                "as relative."
            ),
        },
        "title": lambda: {
            "type": "string",
            "description": (
                "A specific title naming the measure, the cut and the period — "
                "'Premium by Product Line (2024)', not 'Chart'."
            ),
        },
    }
    build = builders.get(name)
    if build is None:
        return None
    schema = build()
    # An enum argument with nothing to offer is dropped rather than emitted
    # empty: an empty enum is unsatisfiable and would fail the whole tool call.
    values = schema.get("enum") or (schema.get("items") or {}).get("enum")
    if values is not None and not values:
        return None
    return schema


# Arguments without which a chart type cannot be drawn at all. `series`,
# `bar_mode`, `sort` and `step_kinds` are deliberately optional — a single-series
# bar with no legend is a perfectly good chart, and forcing the model to supply a
# legend is how 15-entry legends get born.
_REQUIRED = {
    "bar": ("x_category", "y_measures", "title"),
    "line": ("x_temporal", "y_measures", "title"),
    "donut": ("labels", "values", "title"),
    "pie": ("labels", "values", "title"),
    "scatter": ("x_measure", "y_measure", "title"),
    "waterfall": ("x_steps", "y_measure", "title"),
    "combo": ("x_category", "y_amounts", "secondary_y_rates", "title"),
}


def tool_schema(spec: ChartToolSpec, profile: ColumnProfile) -> Optional[Dict[str, Any]]:
    """OpenAI-format function schema for one chart type, or None if unbuildable."""
    properties: Dict[str, Any] = {}
    for name in spec.arguments:
        argument = _argument(name, profile)
        if argument is not None:
            properties[name] = argument

    required = [name for name in _REQUIRED.get(spec.name, ()) if name in properties]
    if len(required) < len(_REQUIRED.get(spec.name, ())):
        return None  # a mandatory axis has no candidate column — withhold the type

    return {
        "type": "function",
        "function": {
            "name": spec.tool_name,
            "description": f"{spec.summary} Use when {spec.use_when}",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def tool_schemas(profile: ColumnProfile) -> List[Dict[str, Any]]:
    """Every chart type this result set supports, as bindable function schemas."""
    schemas = []
    for spec in applicable_types(profile):
        schema = tool_schema(spec, profile)
        if schema is not None:
            schemas.append(schema)
    return schemas


def catalog_text(profile: ChartToolSpec | ColumnProfile) -> str:
    """The offered chart types as text — for prompts and for logs."""
    specs = applicable_types(profile) if isinstance(profile, ColumnProfile) else ()
    return "\n".join(
        f"- {spec.tool_name}: {spec.summary} Use when {spec.use_when}"
        for spec in specs
    )


def type_of(tool_name: str) -> str:
    """The `chart_type` enum value behind a tool name (`draw_bar` -> `bar`)."""
    name = str(tool_name or "").strip().lower()
    name = name[len("draw_"):] if name.startswith("draw_") else name
    return name if name in CATALOG else ""
