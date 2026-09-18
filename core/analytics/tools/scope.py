"""The turn's shared scope — the filters applied to every tool call.

Scope is assembled deterministically, never asked of the model, from what the turn
already resolved:

  1. the query contract's `resolved_filters` (exact stored values, produced once by
     `core.agents.common.contract.resolve_entities` and already reconciled by HITL);
  2. the planner's own `filters`, grounded through the same matcher — this is what
     carries a filter the contract's entity buckets do not model (e.g. a segment the
     planner inferred from the rules);
  3. the year(s) implied by the plan's `timeframe`.

Contract filters win on a key collision: they are the values the user confirmed. A
call's own filters win over all of it (the orchestrator's merge), so a comparison
year on one call still overrides the turn's year.

`TurnScope.blocked` is the safety catch: when the plan named a filter value on a
real column and that value matched nothing, we do NOT compute a wider answer — the
turn falls back to the LLM-SQL path, which has its own fuzzy repair loop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from core.analytics.sql import flow_spec
from core.analytics.tools.grounding import ValueMatcher, ground_filters

# Not `\b`-anchored: a planner timeframe is as likely to read "FY2024" or "Q1 2024"
# as a bare year, and a word boundary refuses the letter-prefixed forms.
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_YEAR_RANGE = re.compile(r"\d{4}\s*(?:-|–|to|through)\s*\d{4}")


@dataclass(frozen=True)
class TurnScope:
    """The filters every call inherits, plus why the scope may be untrustworthy."""

    filters: Dict[str, Any] = field(default_factory=dict)
    unmatched: Tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        """True when a named filter value could not be resolved to stored data."""
        return bool(self.unmatched)


def years_in(timeframe: str) -> List[int]:
    """Every year named in a timeframe string, expanded over an explicit range.

    "2024" -> [2024]; "2023-2024" -> [2023, 2024]; "last 12 months" -> [] (nothing
    to pin — the primitives then see the full history, which is what a rolling
    window wants).
    """
    found = [int(match.group(0)) for match in _YEAR.finditer(timeframe or "")]
    if len(found) == 2 and _YEAR_RANGE.search(timeframe or ""):
        start, end = sorted(found)
        if 0 < end - start <= 10:
            return list(range(start, end + 1))
    return sorted(dict.fromkeys(found))


def _collapse(values: Any) -> Any:
    """A single-item list is a scalar filter; keep longer lists as IN-lists."""
    if isinstance(values, (list, tuple)) and len(values) == 1:
        return values[0]
    return values


def turn_scope(
    flow: str,
    *,
    resolved_filters: Optional[Mapping[str, Any]] = None,
    plan_filters: Optional[Mapping[str, Any]] = None,
    timeframe: str = "",
    user_query: str = "",
    matcher: Optional[ValueMatcher] = None,
) -> TurnScope:
    """The shared filters for this turn, as {column: value | [values]}.

    The year is established from four sources, in this order: the plan's own
    filters, the turn contract's resolved filters, the plan's `timeframe`, and —
    last — the years named in `user_query` itself.

    That last one is a floor, not a preference. The three sources above it are all
    written by a model, and when every one of them omitted a year the turn
    silently computed over the whole history of the book: "Zurich premium in
    Canada for 2025" answered with 2024 and 2025 added together. A year the user
    typed is not a judgement call, and reading it off the question costs nothing.
    """
    spec = flow_spec(flow)
    columns = {name.lower(): name for name in spec.columns}

    filters: Dict[str, Any] = {}
    unmatched: Tuple[str, ...] = ()

    if plan_filters:
        grounded = ground_filters(flow, plan_filters, matcher=matcher)
        unmatched = grounded.unmatched_values
        for column, value in grounded.values.items():
            filters[column] = _collapse(value)

    for column, values in (resolved_filters or {}).items():
        canonical = columns.get(str(column).strip().lower())
        if canonical and values:
            filters[canonical] = _collapse(list(values))

    year_column = spec.date_columns.get("year")
    if year_column and year_column not in filters:
        years = years_in(timeframe) or years_in(user_query)
        if years:
            filters[year_column] = _collapse(years)

    return TurnScope(filters=filters, unmatched=unmatched)


def pin_latest_year(
    flow: str,
    filters: Mapping[str, Any],
    *,
    user_query: str,
    engine: Optional[Any] = None,
) -> Tuple[Dict[str, Any], Optional[int]]:
    """Default a period-less scope to the latest year in the data.

    Both flows' timeframe skills have always stated the rule — a question that
    names no time reference means the latest year, never an all-years aggregate —
    and until now only the deterministic rails applied it. The analytical path
    hands `compute_metric` whatever filters the model wrote, and a model that
    omits the year gets every year in the book silently summed into one figure.
    That is the worst kind of wrong answer: plausible, precise, and off by
    however many years the warehouse holds.

    So the rule lives here, once, and both paths call it. A turn that DOES name a
    timeframe — an explicit year, a quarter, or a multi-period term like YoY or
    trend — is returned untouched: those need more than one year and pinning one
    would break them.

    A question that names an explicit YEAR is pinned to that year rather than
    left alone. This used to bail out on any timeframe reference at all, which
    read as "the turn has said what it wants, do not interfere" — and was wrong
    in the one case that mattered: a question naming a year whose filters had not
    picked it up got no period AND no default, so it silently summed the book.
    A stated year is applied; a quarter or a multi-period term still defers,
    because those need more than one year.

    Returns the filters to use and the year that was DEFAULTED, or ``None`` when
    none was. The caller needs that second value: a default the reader cannot see
    is worse than no default (`core.answers.scope`). A year the reader stated
    themselves is not a default and is reported as ``None`` — there is nothing to
    disclose about giving someone what they asked for.
    """
    from core.analytics.library import get_latest_year
    from core.analytics.timeframe import explicit_years, names_a_timeframe
    from core.analytics.types import PrimitiveArgs

    pinned = dict(filters)
    year_column = flow_spec(flow).date_columns.get("year")
    if not year_column or year_column in pinned:
        return pinned, None
    stated = explicit_years(user_query)
    if stated:
        pinned[year_column] = stated[0] if len(stated) == 1 else stated
        return pinned, None
    if names_a_timeframe(user_query):
        return pinned, None
    facts = get_latest_year(
        PrimitiveArgs(flow=flow, metric="", group_by=(), filters=dict(pinned)),
        engine=engine,
    )
    if not facts:
        return pinned, None
    year = int(facts[0].value)
    pinned[year_column] = year
    return pinned, year
