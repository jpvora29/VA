"""The analytics primitives, described as LLM tools.

One adapter, in one direction: the primitive library (`core.analytics.library.LIBRARY`)
is the source of truth for what can be computed; this module renders each covered
primitive as a *tool descriptor* the model can call — name, business description, and a
JSON schema for its arguments whose enums come from the flow registry.

Why the enums matter: the model no longer writes SQL, and it cannot name a column or a
metric this flow does not have — `group_by` and `metric` are closed lists built from
`flows.yaml` (and, when an engine is supplied, narrowed to the columns the physical
table really carries). That removes the whole "hallucinated column / wrong measure"
class of error before a query is ever built.

Pure and dependency-light: registry + library only — no dspy, no LangChain, no DB
access beyond the cached column introspection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.analytics.library import LIBRARY
from core.analytics.sql import flow_spec, table_columns
from core.registry.spec import FlowSpec

# Roles a column must have to be a legal grouping axis. A measure is what we
# compute, never a cut; a confidential column (CLIENT_NAME) is never grouped by.
_DIMENSION_ROLES = frozenset({"entity", "temporal"})

# A column declared with a cardinality cap this high is an identifier (survey
# ResponseId & friends), not an analytical cut — grouping by it returns one row
# per response, which is never the answer to a business question.
_MAX_DIMENSION_CARD = 1000


@dataclass(frozen=True)
class ToolSpec:
    """One primitive, described for tool selection.

    `flows` pins a tool to the flows whose definition it encodes — a business
    guardrail, not bookkeeping: peer benchmarking for an additive measure is
    `compute_peer_average_total` (the average of peer TOTALS) while an averaged
    metric like a survey score wants `compute_peer_average` (the average per
    response). Exposing only the right one per flow makes the wrong one
    unselectable.
    """

    name: str
    summary: str
    use_when: str
    flows: Tuple[str, ...]
    # flow -> metric used when the caller names none.
    default_metric: Dict[str, str] = field(default_factory=dict)
    # Extra tuning arguments this primitive accepts (e.g. "grain", "top_n").
    options: Tuple[str, ...] = ()
    groupable: bool = True
    # False for the period-reach tools: "what is the latest quarter?" is a question
    # about the calendar, not about a measure, so offering `metric` would only invite
    # a meaningless argument.
    measured: bool = True

    def metric_for(self, flow: str) -> str:
        return self.default_metric.get(flow, "")


_GRAIN = ("grain",)
_TOP_N = ("top_n",)

# The catalog. One entry per library primitive the model may choose; adding a
# primitive to the library plus a row here is the whole extension path — no
# prompt editing, no graph changes.
_SPECS: Tuple[ToolSpec, ...] = (
    ToolSpec(
        name="compute_breakdown",
        summary="The measure totalled per cut (premium by product line, score by attribute).",
        use_when="the question asks for a value, a total, or a split across one or more dimensions.",
        flows=("gpr", "survey"),
        default_metric={"gpr": "premium", "survey": "score"},
    ),
    ToolSpec(
        name="compute_rank",
        summary="Ranks carriers by the measure within each cut, as '#k of N'.",
        use_when="the question asks where a carrier stands, who leads, or for a top/bottom ordering.",
        flows=("gpr", "survey"),
        default_metric={"gpr": "premium", "survey": "score"},
    ),
    ToolSpec(
        name="compute_yoy",
        summary="Year-over-year % change of the measure, per cut, over WHOLE years.",
        use_when=(
            "the question asks about growth, decline, or change between complete "
            "years. If the latest year is partial, prefer compute_yoy_to_date."
        ),
        flows=("gpr", "survey"),
        default_metric={"gpr": "premium", "survey": "score"},
    ),
    ToolSpec(
        name="compute_yoy_to_date",
        summary=(
            "Like-for-like year-over-year %: each year cut off at the same quarter "
            "(or month) the latest year reaches — Q1-Q2 2025 vs Q1-Q2 2024."
        ),
        use_when=(
            "the data stops part-way through the latest year, so a whole-year "
            "comparison would read a partial year as a decline. On a complete year "
            "it returns the same answer as compute_yoy, so it is always safe."
        ),
        flows=("gpr",),
        default_metric={"gpr": "premium"},
        options=_GRAIN,
    ),
    ToolSpec(
        name="get_latest_year",
        summary="The most recent year the data actually reaches.",
        use_when=(
            "you need to know how current the data is, or the question says "
            "'latest', 'current', or 'most recent' without naming a year."
        ),
        flows=("gpr", "survey"),
        groupable=False,
        measured=False,
    ),
    ToolSpec(
        name="get_latest_quarter",
        summary=(
            "The most recent quarter reached, and whether that year is complete "
            "(dims.complete is false when the latest year is only partly loaded)."
        ),
        use_when=(
            "the question asks how current the data is, names a quarter, or asks "
            "for growth — check this first to see whether the latest year is "
            "partial, and if it is, use compute_yoy_to_date rather than compute_yoy."
        ),
        flows=("gpr",),
        options=_GRAIN,
        groupable=False,
        measured=False,
    ),
    ToolSpec(
        name="compute_period_series",
        summary="The measure per calendar period (month or quarter), in chronological order.",
        use_when="the question asks for a monthly or quarterly trend / time series.",
        flows=("gpr",),
        default_metric={"gpr": "premium"},
        options=_GRAIN,
        groupable=False,
    ),
    ToolSpec(
        name="compute_period_change",
        summary="Period-over-period % change (grain='month' is MoM, grain='quarter' is QoQ).",
        use_when="the question asks about month-on-month or quarter-on-quarter movement.",
        flows=("gpr",),
        default_metric={"gpr": "premium"},
        options=_GRAIN,
        groupable=False,
    ),
    ToolSpec(
        name="compute_ttm",
        summary="Trailing-twelve-month rolling totals of the measure.",
        use_when="the question asks for rolling 12 months, TTM, or the last twelve months.",
        flows=("gpr",),
        default_metric={"gpr": "premium"},
        groupable=False,
    ),
    ToolSpec(
        name="compute_share_of_portfolio",
        summary="Appetite: each cut's premium as a % of the carrier's OWN book.",
        use_when="the question asks about appetite, portfolio mix, or share of portfolio.",
        flows=("gpr",),
        default_metric={"gpr": "premium"},
    ),
    ToolSpec(
        name="compute_share_of_wallet",
        summary="Share of Wallet: the carrier's premium as a % of TOTAL market premium per cut.",
        use_when="the question asks about share of wallet, SoW, or share of the Marsh book.",
        flows=("gpr",),
        default_metric={"gpr": "premium"},
    ),
    ToolSpec(
        name="compute_market_presence",
        summary="Total market (Marsh book) premium per cut — the carrier filter is dropped.",
        use_when="the question needs market or Marsh context rather than one carrier's own number.",
        flows=("gpr",),
        default_metric={"gpr": "premium"},
    ),
    ToolSpec(
        name="compute_peer_average_total",
        summary="Average of each peer's TOTAL premium — the like-for-like peer benchmark for premium.",
        use_when="the question compares a carrier's premium against its peers or the peer average.",
        flows=("gpr",),
        default_metric={"gpr": "premium"},
        groupable=False,
    ),
    ToolSpec(
        name="compute_peer_average",
        summary="The peer group's average score per cut (aggregate only, never a peer name).",
        use_when="the question compares a carrier's survey score against its peers.",
        flows=("survey",),
        default_metric={"survey": "score"},
    ),
    ToolSpec(
        name="compute_nps",
        summary="Net Promoter Score per cut: %promoters (>=9) minus %detractors (<=6).",
        use_when="the question asks about NPS or net promoter score.",
        flows=("survey",),
        default_metric={"survey": "nps"},
    ),
    ToolSpec(
        name="compute_attribute_breakdown",
        summary="Average survey score per section / attribute cut.",
        use_when="the question asks how a carrier is perceived across sections or attributes.",
        flows=("survey",),
        default_metric={"survey": "score"},
    ),
    ToolSpec(
        name="find_whitespace",
        summary="Cuts where the carrier writes ~no premium but the market is materially present.",
        use_when="the question asks about whitespace, gaps, untapped or missing segments.",
        flows=("gpr",),
        default_metric={"gpr": "premium"},
        options=_TOP_N,
    ),
    ToolSpec(
        name="find_service_gaps",
        summary="Cuts where the carrier's score falls materially below its peer average.",
        use_when="the question asks where a carrier underperforms peers on perception or service.",
        flows=("survey",),
        default_metric={"survey": "score"},
        options=_TOP_N,
    ),
)

# Name -> spec. Only primitives the library really exposes are catalogued, so a
# stale row can never be selected.
CATALOG: Dict[str, ToolSpec] = {
    spec.name: spec for spec in _SPECS if spec.name in LIBRARY
}


def tool_catalog(flow: str) -> Tuple[ToolSpec, ...]:
    """The tools available to `flow`, in catalog order."""
    return tuple(spec for spec in CATALOG.values() if flow in spec.flows)


def tool_names(flow: str) -> Tuple[str, ...]:
    """Just the names — the allowlist a selected call is validated against."""
    return tuple(spec.name for spec in tool_catalog(flow))


def dimension_columns(
    spec: FlowSpec, *, engine: Optional[Any] = None
) -> Tuple[str, ...]:
    """Columns this flow may group by: declared dimensions, minus confidential ones.

    With an `engine`, the list is narrowed to the columns the physical primary
    table actually has — the registry declares both spellings of some survey
    columns (Section/Sections) and only one of them exists in a given warehouse.
    """
    names = [
        col.name
        for col in spec.columns.values()
        if col.role in _DIMENSION_ROLES
        and not col.confidential
        and col.card_cap <= _MAX_DIMENSION_CARD
    ]
    if engine is not None:
        present = table_columns(engine, spec.primary_table)
        if present:
            names = [name for name in names if name in present]
    return tuple(names)


def metric_names(spec: FlowSpec) -> Tuple[str, ...]:
    """The flow's metric names — the closed list a tool's `metric` may take."""
    return tuple(spec.metrics)


def _parameters(
    tool: ToolSpec, spec: FlowSpec, dimensions: Tuple[str, ...]
) -> Dict[str, Any]:
    """JSON schema for one tool's arguments, with registry-derived enums."""
    properties: Dict[str, Any] = {}
    if tool.measured:
        properties["metric"] = {
            "type": "string",
            "enum": list(metric_names(spec)),
            "description": "Measure to compute over. Omit to use this flow's default.",
        }
    if tool.groupable:
        properties["group_by"] = {
            "type": "array",
            "items": {"type": "string", "enum": list(dimensions)},
            "description": (
                "Dimension column(s) to cut by. Leave empty for a single total. "
                "Only column names belong here, never a filter value."
            ),
        }
    properties["filters"] = {
        "type": "object",
        "description": (
            "Filters for THIS call only, as {column: value}. The turn's carrier / "
            "country / year scope is applied automatically — add something only when "
            "the scope does not already carry it (e.g. a comparison year)."
        ),
        "additionalProperties": {"type": "string"},
    }
    if "grain" in tool.options:
        properties["grain"] = {
            "type": "string",
            "enum": ["month", "quarter"],
            "description": "Calendar bucket for the period series.",
        }
    if "top_n" in tool.options:
        properties["top_n"] = {
            "type": "integer",
            "description": "How many ranked results to return (default 3).",
        }
    return {"type": "object", "properties": properties, "required": []}


def tool_schemas(flow: str, *, engine: Optional[Any] = None) -> List[Dict[str, Any]]:
    """OpenAI-format function schemas for `flow` — what gets bound to the model."""
    spec = flow_spec(flow)
    dimensions = dimension_columns(spec, engine=engine)
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": f"{tool.summary} Use when {tool.use_when}",
                "parameters": _parameters(tool, spec, dimensions),
            },
        }
        for tool in tool_catalog(flow)
    ]


def catalog_text(flow: str) -> str:
    """The tool menu as text — for prompts that cannot bind schemas, and for logs."""
    return "\n".join(
        f"- {tool.name}: {tool.summary} Use when {tool.use_when}"
        for tool in tool_catalog(flow)
    )
