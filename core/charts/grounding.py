"""Turn a chart tool call into the `ChartOutput` dict the renderer already speaks.

The agent picks a tool (`draw_bar`, `draw_combo`, …) with per-type arguments; every
downstream consumer — `ui.chart_functions.generate_chart`, the Boardroom store, the
PPT exporter — reads one flat spec dict with `chart_type / x / y / series /
bar_mode / secondary_y / waterfall_measures / sort / title`. This module is the one
adapter between those two shapes.

It is also the second gate. The schemas make most nonsense unrepresentable, but a
model can still return a column name in the wrong case, or a `bar_mode` with no
series to apply it to. Grounding resolves names against the real columns and drops
what cannot apply, reporting every change — and REJECTS (returns nothing) when the
call is missing an axis it cannot be drawn without, which is the signal to fall
back to the previous chart path rather than draw something wrong.

Pure functions; no LLM, no DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.charts.catalog import CATALOG, type_of
from core.charts.profile import ColumnProfile


@dataclass(frozen=True)
class GroundedChart:
    """A chart call proven drawable: known type, real columns, coherent options."""

    spec: Mapping[str, Any]
    repairs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RejectedChart:
    """A call that cannot be drawn as asked, and why."""

    name: str
    reason: str


@dataclass(frozen=True)
class ChartGrounding:
    """What survived grounding."""

    chart: Optional[GroundedChart] = None
    rejected: Tuple[RejectedChart, ...] = ()
    repairs: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.chart is not None


def _resolver(profile: ColumnProfile):
    """Case/underscore-insensitive column lookup against the real result columns."""
    lookup = {
        str(name).strip().lower().replace("_", " "): name for name in profile.roles
    }

    def resolve(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if text in profile.roles:
            return text
        return lookup.get(text.lower().replace("_", " "))

    return resolve


def _columns(value: Any, resolve) -> List[str]:
    """Resolve a scalar-or-list argument to a de-duplicated list of real columns."""
    values = value if isinstance(value, (list, tuple)) else [value]
    resolved = [resolve(item) for item in values]
    return list(dict.fromkeys([col for col in resolved if col]))


def _first(value: Any, resolve) -> Optional[str]:
    columns = _columns(value, resolve)
    return columns[0] if columns else None


def ground_chart_call(
    tool_name: str,
    arguments: Mapping[str, Any],
    profile: ColumnProfile,
) -> ChartGrounding:
    """Ground one selected chart tool call into a renderer-ready spec.

    Returns a `ChartGrounding` whose `chart` is None when the call cannot be
    drawn — the caller's signal to fall back, never to guess.
    """
    chart_type = type_of(tool_name)
    if not chart_type:
        return ChartGrounding(rejected=(RejectedChart(str(tool_name), "unknown chart type"),))

    resolve = _resolver(profile)
    repairs: List[str] = []
    args = dict(arguments or {})

    builder = _BUILDERS.get(chart_type)
    spec, reason = builder(args, resolve, profile, repairs)
    if spec is None:
        return ChartGrounding(rejected=(RejectedChart(tool_name, reason),))

    spec["chart_type"] = chart_type
    spec.setdefault("title", str(args.get("title") or "").strip())
    spec.setdefault("series", [])
    spec.setdefault("bar_mode", [])
    spec.setdefault("secondary_y", [])
    spec.setdefault("waterfall_measures", [])
    spec.setdefault("sort", "none")
    spec.setdefault("y_agg", _aggregation_for(spec, profile))
    # A legend that separates nothing is noise; the renderer reads this flag.
    spec["is_legend"] = bool(spec.get("series"))
    return ChartGrounding(
        chart=GroundedChart(spec=spec, repairs=tuple(repairs)), repairs=tuple(repairs)
    )


def _aggregation_for(spec: Mapping[str, Any], profile: ColumnProfile) -> str:
    """How to combine rows that share an x/series key: mean for rates, sum for amounts.

    The renderer aggregates whenever several rows land on the same x, and its own
    default is `sum` — which quietly adds up percentages and scores. Chartwright
    knows each measure's role, so it can say which is right.

    One caveat, stated rather than hidden: the renderer applies ONE aggregation to
    every measure on the chart, so a combo mixing an amount with a rate cannot have
    both. We choose for the majority (the bars), which is the same compromise the
    renderer already makes — a combo's x is normally unique per row anyway, so no
    aggregation happens at all.
    """
    measures = list(spec.get("y") or []) + list(spec.get("secondary_y") or [])
    if measures and all(col in profile.rates for col in measures):
        return "mean"
    return "sum"


# ── one builder per chart type ───────────────────────────────────────────────
#
# Each returns `(spec_or_None, reason)`. They share the same rule: an axis the
# type cannot be drawn without is a rejection; an optional extra that cannot apply
# is dropped with a recorded repair.


def _series_and_mode(
    args: Mapping[str, Any], resolve, profile: ColumnProfile, repairs: List[str], x: str
) -> Tuple[List[str], List[str]]:
    """The legend columns and their bar modes, minus anything that cannot apply."""
    series = [col for col in _columns(args.get("series"), resolve) if col != x]
    dropped = len(_columns(args.get("series"), resolve)) - len(series)
    if dropped:
        repairs.append("dropped a series column that duplicates the x axis")
    mode = str(args.get("bar_mode") or "").strip().lower()
    if series and mode not in ("group", "stack"):
        mode = "group"
        repairs.append("defaulted bar_mode to 'group'")
    if not series and mode:
        repairs.append("dropped bar_mode (no series to apply it to)")
        mode = ""
    return series, ([mode] * len(series) if series and mode else [])


def _build_bar(args, resolve, profile, repairs):
    x = _first(args.get("x_category"), resolve)
    y = _columns(args.get("y_measures"), resolve)
    if not x or not y:
        return None, "bar needs an x category and at least one y measure"
    series, bar_mode = _series_and_mode(args, resolve, profile, repairs, x)
    sort = str(args.get("sort") or "none").strip().lower()
    if sort not in ("asc", "desc", "none"):
        sort = "none"
    # Sorting a period axis by value scrambles the timeline.
    if sort != "none" and x in profile.temporal:
        repairs.append("kept chronological order on a time axis instead of sorting")
        sort = "none"
    return {"x": x, "y": y, "series": series, "bar_mode": bar_mode, "sort": sort}, ""


def _build_line(args, resolve, profile, repairs):
    x = _first(args.get("x_temporal"), resolve)
    y = _columns(args.get("y_measures"), resolve)
    if not x or not y:
        return None, "line needs a time column and at least one y measure"
    series, _ = _series_and_mode(args, resolve, profile, repairs, x)
    return {"x": x, "y": y, "series": series}, ""


def _build_part_to_whole(args, resolve, profile, repairs):
    labels = _first(args.get("labels"), resolve)
    values = _first(args.get("values"), resolve)
    if not labels or not values:
        return None, "a part-to-whole chart needs a label column and a measure"
    return {"x": labels, "y": [values], "series": []}, ""


def _build_scatter(args, resolve, profile, repairs):
    x = _first(args.get("x_measure"), resolve)
    y = _first(args.get("y_measure"), resolve)
    if not x or not y:
        return None, "scatter needs two measures"
    if x == y:
        return None, "scatter needs two DIFFERENT measures"
    # Time on a scatter axis produces fractional year ticks; the critic converts
    # such a spec to a line, so refuse it here rather than manufacture the problem.
    if x in profile.temporal or y in profile.temporal:
        return None, "scatter cannot take a time column on an axis"
    series = _columns(args.get("series"), resolve)
    return {"x": x, "y": [y], "series": series}, ""


def _build_waterfall(args, resolve, profile, repairs):
    x = _first(args.get("x_steps"), resolve)
    y = _first(args.get("y_measure"), resolve)
    if not x or not y:
        return None, "waterfall needs a step column and a measure"
    kinds = [
        str(k).strip().lower()
        for k in (args.get("step_kinds") or [])
        if str(k).strip().lower() in ("relative", "total")
    ]
    return {"x": x, "y": [y], "series": [], "waterfall_measures": kinds}, ""


def _build_combo(args, resolve, profile, repairs):
    x = _first(args.get("x_category"), resolve)
    amounts = _columns(args.get("y_amounts"), resolve)
    rates = [
        col for col in _columns(args.get("secondary_y_rates"), resolve)
        if col not in amounts
    ]
    if not x or not amounts or not rates:
        return None, "combo needs an x axis, a bar measure and a secondary-axis rate"
    return {"x": x, "y": amounts, "series": [], "secondary_y": rates}, ""


_BUILDERS = {
    "bar": _build_bar,
    "line": _build_line,
    "pie": _build_part_to_whole,
    "donut": _build_part_to_whole,
    "scatter": _build_scatter,
    "waterfall": _build_waterfall,
    "combo": _build_combo,
}

# Every catalogued type must have a builder, or it could be offered and then
# never drawn. Checked at import so a new type cannot be half-added.
assert set(_BUILDERS) == set(CATALOG), "chart catalog and grounding builders disagree"
