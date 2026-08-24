"""Ground a selected tool call against the flow registry — deterministic, no LLM.

The model picks WHICH calculation to run; this module decides whether that call is
runnable, and rewrites it into the exact names the data uses:

  - the primitive must be in this flow's catalog;
  - every `group_by` column must be a declared (and physically present) dimension;
  - the `metric` must resolve through the registry, else the tool's flow default;
  - every filter column must exist, and its value is matched to the exact stored
    value (fuzzy, via the shared matcher) rather than trusted verbatim.

Anything that fails is REJECTED with a reason, never silently repaired into a
different question — a rejected call is the signal to fall back to the LLM-SQL
path. Pure functions throughout; the value matcher is injected (lazily defaulting
to the shared `match_column_values`) so this module unit-tests without the data
layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from core.analytics.sql import find_metric, flow_spec
from core.analytics.tools.catalog import CATALOG, ToolSpec, dimension_columns

# (flow, column, term) -> exact stored values, best match first.
ValueMatcher = Callable[[str, str, str], List[str]]


@dataclass(frozen=True)
class GroundedCall:
    """A tool call proven runnable: registered primitive, real columns, exact values."""

    name: str
    metric: str = ""
    group_by: Tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        """Human-readable call signature — provenance for logs and the UI."""
        parts = [f"metric={self.metric or 'default'}"]
        if self.group_by:
            parts.append(f"group_by={list(self.group_by)}")
        if self.filters:
            parts.append(f"filters={dict(self.filters)}")
        if self.options:
            parts.append(f"options={dict(self.options)}")
        return f"{self.name}({', '.join(parts)})"


@dataclass(frozen=True)
class RejectedCall:
    """A call that cannot be run as asked, and why."""

    name: str
    reason: str


@dataclass(frozen=True)
class GroundingResult:
    """What survived grounding, and what did not."""

    calls: Tuple[GroundedCall, ...] = ()
    rejected: Tuple[RejectedCall, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.calls)


def _default_matcher() -> ValueMatcher:
    """The shared fuzzy matcher, imported lazily (it pulls the data layer)."""

    def match(flow: str, column: str, term: str) -> List[str]:
        from core.mcp.tools import match_column_values

        return match_column_values(flow, column, term)

    return match


def _get(call: Any, key: str, default: Any) -> Any:
    """Read a field off a duck-typed call (pydantic model, dataclass, or dict)."""
    if isinstance(call, Mapping):
        return call.get(key, default)
    value = getattr(call, key, default)
    return default if value is None else value


def _ground_metric(tool: ToolSpec, flow: str, requested: Any) -> Optional[str]:
    """The registry-resolved metric name, or the tool's flow default. None = unusable."""
    spec = flow_spec(flow)
    requested = str(requested or "").strip()
    if requested:
        resolved = find_metric(spec, requested)
        if resolved is not None:
            return resolved.name
    return tool.metric_for(flow) or None


def _ground_group_by(
    tool: ToolSpec, flow: str, requested: Any, *, engine: Optional[Any]
) -> Tuple[Tuple[str, ...], List[str]]:
    """Keep the requested cuts that are real dimensions; report the ones dropped."""
    if not tool.groupable:
        return (), []
    spec = flow_spec(flow)
    allowed = {name.lower(): name for name in dimension_columns(spec, engine=engine)}
    kept: List[str] = []
    dropped: List[str] = []
    for column in requested or ():
        canonical = allowed.get(str(column).strip().lower())
        if canonical is None:
            dropped.append(str(column))
        elif canonical not in kept:
            kept.append(canonical)
    return tuple(kept), dropped


def _ground_filter_value(
    flow: str, column: str, value: Any, *, matcher: ValueMatcher
) -> Any:
    """The exact stored value(s) for a filter, or None when nothing matches.

    Numbers (Year) pass through untouched; a list stays a list (the SQL builder
    turns it into an IN clause). A string that matches nothing is a *rejection*,
    not a pass-through: an unmatched filter value is how a turn silently answers
    a different question.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple, set)):
        matched = [
            grounded
            for item in value
            if (grounded := _ground_filter_value(flow, column, item, matcher=matcher))
            is not None
        ]
        return matched or None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    matches = matcher(flow, column, text)
    return matches[0] if matches else None


@dataclass(frozen=True)
class FilterGrounding:
    """Filters that grounded, and the two ways one can fail.

    The distinction matters: an *unknown column* is usually planner noise
    ("timeframe": "latest") and is safely ignored, whereas an *unmatched value* on
    a real column means the turn asked about something we could not find — running
    anyway would answer a different, wider question than the one asked.
    """

    values: Dict[str, Any] = field(default_factory=dict)
    unknown_columns: Tuple[str, ...] = ()
    unmatched_values: Tuple[str, ...] = ()

    @property
    def dropped(self) -> Tuple[str, ...]:
        return self.unknown_columns + self.unmatched_values


def ground_filters(
    flow: str, requested: Any, *, matcher: Optional[ValueMatcher] = None
) -> FilterGrounding:
    """Ground each filter to a real column and an exact stored value.

    Shared with the scope builder, which grounds the planner's filters the same
    way the model's own call filters are grounded.
    """
    matcher = matcher or _default_matcher()
    spec = flow_spec(flow)
    columns = {name.lower(): name for name in spec.columns}
    grounded: Dict[str, Any] = {}
    unknown: List[str] = []
    unmatched: List[str] = []
    for column, value in (requested or {}).items():
        canonical = columns.get(str(column).strip().lower())
        if canonical is None:
            unknown.append(str(column))
            continue
        resolved = _ground_filter_value(flow, canonical, value, matcher=matcher)
        if resolved is None:
            unmatched.append(f"{column}={value}")
            continue
        grounded[canonical] = resolved
    return FilterGrounding(
        values=grounded,
        unknown_columns=tuple(unknown),
        unmatched_values=tuple(unmatched),
    )


def _ground_options(tool: ToolSpec, call: Any) -> Dict[str, Any]:
    """Tuning arguments the primitive declares (grain, top_n) — others ignored."""
    options: Dict[str, Any] = {}
    for name in tool.options:
        value = _get(call, name, None)
        if value in (None, ""):
            continue
        if name == "top_n":
            try:
                options[name] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            options[name] = str(value)
    return options


def ground_call(
    flow: str,
    call: Any,
    *,
    matcher: Optional[ValueMatcher] = None,
    engine: Optional[Any] = None,
) -> Tuple[Optional[GroundedCall], Optional[RejectedCall]]:
    """Ground one call. Exactly one half of the pair is populated."""
    name = str(_get(call, "name", "") or "").strip()
    tool = CATALOG.get(name)
    if tool is None or flow not in tool.flows:
        return None, RejectedCall(name or "<unnamed>", "not a tool for this flow")

    metric = _ground_metric(tool, flow, _get(call, "metric", ""))
    if metric is None:
        return None, RejectedCall(name, "no metric resolved for this flow")

    group_by, dropped_cuts = _ground_group_by(
        tool, flow, _get(call, "group_by", ()), engine=engine
    )
    if dropped_cuts:
        return None, RejectedCall(name, f"unknown group_by column(s): {dropped_cuts}")

    filters = ground_filters(
        flow, _get(call, "filters", {}), matcher=matcher or _default_matcher()
    )
    if filters.dropped:
        # A call must be runnable EXACTLY as asked; a partially-applied filter set
        # answers a different question. Rejection routes the turn to LLM-SQL.
        return None, RejectedCall(name, f"ungrounded filter(s): {list(filters.dropped)}")

    return (
        GroundedCall(
            name=name,
            metric=metric,
            group_by=group_by,
            filters=filters.values,
            options=_ground_options(tool, call),
        ),
        None,
    )


def ground_calls(
    flow: str,
    calls: Optional[Sequence[Any]],
    *,
    matcher: Optional[ValueMatcher] = None,
    engine: Optional[Any] = None,
) -> GroundingResult:
    """Ground every selected call, dropping duplicates (same primitive, same args)."""
    matcher = matcher or _default_matcher()
    grounded: List[GroundedCall] = []
    rejected: List[RejectedCall] = []
    seen: set = set()
    for call in calls or ():
        ok, bad = ground_call(flow, call, matcher=matcher, engine=engine)
        if bad is not None:
            rejected.append(bad)
            continue
        key = (
            ok.name,
            ok.metric,
            ok.group_by,
            tuple(sorted((k, str(v)) for k, v in ok.filters.items())),
            tuple(sorted((k, str(v)) for k, v in ok.options.items())),
        )
        if key in seen:
            continue
        seen.add(key)
        grounded.append(ok)
    return GroundingResult(calls=tuple(grounded), rejected=tuple(rejected))
