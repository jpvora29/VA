"""Tool calling over the deterministic analytics library — the SQL agent's replacement.

The old path asked the model to re-derive a SQL recipe we already own, every turn,
and then repaired the result in a fixer loop. This path asks the model the only
question it is actually good at — *which calculation answers this?* — and runs the
calculation itself:

    plan + query ─► select (LLM, tool calls) ─► ground (registry) ─► compute (library)
                                                        │
                                                        └─ nothing runnable ⇒ LLM-SQL fallback

Design:

- **Strategy** — `ToolSelector` is a one-method protocol. `PlanToolSelector` reads the
  primitive calls the planner already emitted (free); `LLMToolSelector` binds the
  flow's tool schemas to the model and reads back `tool_calls`; `ChainedToolSelector`
  tries them in order. `make_tool_selector` is the factory.
- **Dependency injection** — the runner takes its selector, orchestrator, matcher and
  engine, so every branch is testable without a model or a warehouse.
- **Deterministic edges** — grounding, scope and row shaping are pure functions in
  `core.analytics.tools`; only selection touches an LLM.

Flag: ``ANALYTICS_TOOLS`` = ``on`` (default) | ``plan`` (no extra LLM call) |
``off`` (restores the pure LLM-SQL path).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from core.analytics.library import get_latest_year
from core.analytics.orchestrator import AnalyticsOrchestrator
from core.analytics.sql import flow_spec
from core.analytics.timeframe import names_a_timeframe
from core.analytics.tools import (
    GroundedCall,
    TurnScope,
    ValueMatcher,
    catalog_text,
    facts_digest,
    facts_to_rows,
    ground_calls,
    tool_schemas,
    turn_scope,
)
from core.analytics.types import AnalyticsFact, PrimitiveArgs
from core.observability import log_event
from logger import get_logger

logger = get_logger(__name__)

# Row count above which the UI shows the download instead of a table. Mirrors the
# execute-SQL tool's threshold so both paths overflow at the same size.
OVERFLOW_ROW_LIMIT = 40


def analytics_tools_mode() -> str:
    """`on` (default), `plan`, or `off` — see the module docstring."""
    return os.getenv("ANALYTICS_TOOLS", "on").strip().lower()


def analytics_tools_enabled() -> bool:
    return analytics_tools_mode() != "off"


# ── selection (the one LLM step) ─────────────────────────────────────────────


@dataclass(frozen=True)
class SelectionRequest:
    """Everything a selector needs to choose calculations for this turn."""

    flow: str
    user_query: str
    plan_json: str = ""
    scope: Mapping[str, Any] = field(default_factory=dict)
    engine: Optional[Any] = None


class ToolSelector(Protocol):
    """Chooses which analytics tools to call. Returns raw (ungrounded) calls."""

    def select(self, request: SelectionRequest) -> List[Dict[str, Any]]:
        ...


class PlanToolSelector:
    """Reads the primitive calls the planner already emitted — zero LLM calls.

    `AnalyticalPlan.primitives` is part of the planner contract, so when the plan
    names its calculations there is nothing left to decide.
    """

    def select(self, request: SelectionRequest) -> List[Dict[str, Any]]:
        try:
            plan = json.loads(request.plan_json or "{}")
        except (TypeError, ValueError):
            return []
        calls = plan.get("primitives") or []
        return [call for call in calls if isinstance(call, dict) and call.get("name")]


_SELECTOR_PROMPT = """
[ROLE]
You choose which pre-built analytics functions answer an insurance data question.
You do NOT write SQL and you do NOT produce numbers — each function computes its own
number from the database using a definition the business has already signed off.

[HOW TO CHOOSE]
- Call every function needed to answer the question fully, and no more. A comparison
  ("how does X compare with peers") needs both the carrier figure and the peer figure.
- `group_by` is the dimension the answer is cut BY. Omit it for a single total.
- The turn's scope — carrier, country, year — is applied to every call automatically.
  Only pass `filters` for something the scope does not carry (e.g. a comparison year).
- Prefer the function whose description names the metric the user asked for
  (appetite -> share of portfolio, SoW -> share of wallet, gaps -> whitespace).

[GROWTH AND PARTIAL YEARS]
The warehouse is often loaded only part-way through the latest year. Comparing that
stub against a complete prior year reports a collapse that did not happen.
- For ANY growth / decline / YoY question, also call `get_latest_quarter`. Its
  `complete` flag says whether the latest year is whole.
- When the latest year is partial, use `compute_yoy_to_date` (it truncates BOTH years
  to the same quarter) instead of `compute_yoy`. On a complete year the two agree, so
  `compute_yoy_to_date` is never the wrong choice.
- Say which span the comparison covers when it is not a whole year — the fact carries
  it in `through` (e.g. "through Q2").

[WHEN NOT TO CALL]
If no function computes what was asked — a bare list of rows, a lookup, a count, an
exotic derived measure — make NO tool call and reply with the single word NONE. That
routes the question to the general SQL path, which is the right answer for it.

[AVAILABLE FUNCTIONS]
{catalog}
""".strip()


class LLMToolSelector:
    """Binds the flow's tool schemas to the model and reads back its calls.

    The schemas' enums come from the flow registry, so a column or metric this flow
    does not have is not expressible — the model cannot name it, let alone query it.
    """

    def __init__(self, *, llm: Optional[Any] = None) -> None:
        self._llm = llm

    def _client(self) -> Any:
        # Lazy: importing this module must not pull the LLM/credential layer.
        if self._llm is not None:
            return self._llm
        from core.initialization import Initialization

        return Initialization.llm_balanced

    def select(self, request: SelectionRequest) -> List[Dict[str, Any]]:
        from langchain_core.messages import HumanMessage, SystemMessage

        schemas = tool_schemas(request.flow, engine=request.engine)
        if not schemas:
            return []

        messages = [
            SystemMessage(
                content=_SELECTOR_PROMPT.format(catalog=catalog_text(request.flow))
            ),
            HumanMessage(
                content=(
                    f"Question: {request.user_query}\n"
                    f"Scope already applied: {dict(request.scope)}\n"
                    f"Analytical plan:\n{request.plan_json or '(none)'}"
                )
            ),
        ]

        response = self._client().bind_tools(schemas).invoke(messages)
        calls = []
        for call in getattr(response, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
            if name:
                calls.append({"name": name, **(args or {})})
        return calls


class ChainedToolSelector:
    """Tries each selector in order and returns the first non-empty selection."""

    def __init__(self, *selectors: ToolSelector) -> None:
        self._selectors = selectors

    def select(self, request: SelectionRequest) -> List[Dict[str, Any]]:
        for selector in self._selectors:
            try:
                calls = selector.select(request)
            except Exception:  # noqa: BLE001 - selection must never sink the turn
                logger.exception("tool selection failed in %s", type(selector).__name__)
                continue
            if calls:
                return calls
        return []


def make_tool_selector(
    mode: Optional[str] = None, *, llm: Optional[Any] = None
) -> Optional[ToolSelector]:
    """Build the selector for `mode` (default: the ANALYTICS_TOOLS env flag)."""
    mode = (mode or analytics_tools_mode()).strip().lower()
    if mode == "off":
        return None
    if mode == "plan":
        return PlanToolSelector()
    return ChainedToolSelector(PlanToolSelector(), LLMToolSelector(llm=llm))


def compute_first_directive(flow: str, route: str) -> str:
    """The calculations available BY NAME, plus the rule preferring them over SQL.

    `compute_metric` already carries this menu in its own tool description, but a
    tool description is read when a tool is called — not when the solver decides
    HOW to answer. By then the prompt has already said "use run_sql", the lens has
    handed over a SQL shape, and the domain rules have described the query to
    write, so a signed-off calculation loses to a hand-derived query it should
    always beat. Naming the covered calculations here, at the point of choice, is
    what makes the tested primitive the default instead of the exception.

    Returns "" when the analytics library is switched off, so the prompt falls
    back to its pure-SQL form byte-identically.
    """
    if not analytics_tools_enabled():
        return ""
    flows = ["gpr", "survey"] if route == "both" else [flow]
    menus = "\n\n".join(
        f"{name.upper()}:\n{catalog_text(name)}"
        for name in flows
        if catalog_text(name)
    )
    if not menus:
        return ""
    return f"""[CALCULATIONS AVAILABLE BY NAME — PREFER THESE OVER run_sql]
Each calculation below is a definition the business has signed off, computed by a
tested function. Call it by name:

    compute_metric(flow=..., name=..., metric=..., group_by=[...], filters={{...}})

It resolves the peer set for you, matches filter values to the exact stored
values, and returns the same number every time. Writing the SQL for one of these
by hand re-derives a known recipe under time pressure and can silently disagree
with the rest of the product — so reach for the named calculation FIRST, and use
run_sql only for what no calculation below covers.

{menus}"""


# ── running the selected calls ───────────────────────────────────────────────


@dataclass(frozen=True)
class AnalyticsTurn:
    """What the tool path produced for one turn."""

    rows: List[Dict[str, Any]] = field(default_factory=list)
    facts: List[AnalyticsFact] = field(default_factory=list)
    calls: Tuple[GroundedCall, ...] = ()
    scope: Mapping[str, Any] = field(default_factory=dict)
    rejected: Tuple[str, ...] = ()
    skipped: Tuple[str, ...] = ()
    # Set when the turn named no period and the scope fell back to the latest year.
    # The flows' timeframe skills require the answer to SAY which year it defaulted
    # to, so this has to travel to the writer rather than stay a private decision.
    defaulted_year: Optional[int] = None

    @property
    def covered(self) -> bool:
        """True when the library answered the question — no SQL fallback needed."""
        return bool(self.rows)

    @property
    def overflow(self) -> bool:
        return len(self.rows) > OVERFLOW_ROW_LIMIT

    def provenance(self) -> str:
        """The calculations that produced the rows, as a SQL comment block.

        The turn ran no generated SQL, but the places that display "the query used"
        (pitch workflow, debug views) still deserve an honest answer.
        """
        lines = ["-- computed by the analytics library (no generated SQL)"]
        lines += [f"--   {call.describe()}" for call in self.calls]
        if self.scope:
            lines.append(f"--   scope: {dict(self.scope)}")
        return "\n".join(lines)


class AnalyticsToolRunner:
    """Facade over the tool path: select -> ground -> compute -> shape.

    Every collaborator is injected, so a test drives the whole pipeline with a stub
    selector and an in-memory engine, and production wiring is one factory call.
    """

    def __init__(
        self,
        *,
        selector: Optional[ToolSelector] = None,
        orchestrator: Optional[AnalyticsOrchestrator] = None,
        matcher: Optional[ValueMatcher] = None,
    ) -> None:
        self._selector = selector if selector is not None else make_tool_selector()
        self._orchestrator = orchestrator or AnalyticsOrchestrator()
        self._matcher = matcher

    @property
    def enabled(self) -> bool:
        return self._selector is not None

    def run(
        self,
        *,
        flow: str,
        user_query: str,
        plan_json: str = "",
        resolved_filters: Optional[Mapping[str, Any]] = None,
        subject: Optional[str] = None,
        peers: Optional[Sequence[str]] = None,
        engine: Optional[Any] = None,
    ) -> AnalyticsTurn:
        """Answer this turn from the library, or return an empty (uncovered) turn."""
        if self._selector is None:
            return AnalyticsTurn()

        plan = _parse_plan(plan_json)
        scope = turn_scope(
            flow,
            resolved_filters=resolved_filters,
            plan_filters=plan.get("filters"),
            timeframe=str(plan.get("timeframe") or ""),
            matcher=self._matcher,
        )
        year_column = flow_spec(flow).date_columns.get("year")
        before = scope.filters.get(year_column) if year_column else None
        scope = _pin_latest_year(
            flow, scope, user_query=user_query, engine=engine
        )
        after = scope.filters.get(year_column) if year_column else None
        defaulted_year = after if before is None and after is not None else None
        if scope.blocked:
            # The turn named something we cannot find in the data. Computing a
            # wider answer would be confidently wrong — hand it to the SQL path.
            return AnalyticsTurn(
                scope=scope.filters,
                rejected=tuple(f"scope: unmatched {t}" for t in scope.unmatched),
            )

        selected = self._selector.select(
            SelectionRequest(
                flow=flow,
                user_query=user_query,
                plan_json=plan_json,
                scope=scope.filters,
                engine=engine,
            )
        )
        if not selected:
            return AnalyticsTurn(scope=scope.filters)

        grounding = ground_calls(
            flow, selected, matcher=self._matcher, engine=engine
        )
        rejected = tuple(f"{r.name}: {r.reason}" for r in grounding.rejected)
        # All or nothing: a rejected call means part of the question would go
        # unanswered, and a half-answer read as a whole one is the failure mode
        # this path exists to remove. One fallback beats two partial truths.
        if rejected or not grounding.calls:
            return AnalyticsTurn(scope=scope.filters, rejected=rejected)

        evidence = self._orchestrator.run(
            [_as_call(call) for call in grounding.calls],
            flow=flow,
            shared_filters=scope.filters,
            engine=engine,
            subject=subject or _subject_from(flow, scope.filters),
            peers=peers,
        )
        if evidence.skipped:  # a primitive failed — same all-or-nothing rule
            return AnalyticsTurn(
                scope=scope.filters,
                rejected=rejected,
                skipped=tuple(evidence.skipped),
            )
        return AnalyticsTurn(
            rows=facts_to_rows(evidence.facts),
            facts=list(evidence.facts),
            calls=grounding.calls,
            scope=scope.filters,
            rejected=rejected,
            skipped=tuple(evidence.skipped),
            defaulted_year=defaulted_year,
        )


def _plan_stating_timeframe(plan_json: str, year: int) -> str:
    """The plan with its timeframe set to the year the scope actually used.

    The writers read the plan as `query_plan`, and the timeframe skills require the
    answer to say which year it defaulted to ("for 2025, the latest available year").
    A default the reader cannot see is worse than no default, so the resolved year is
    written back into the field the planner would itself have filled.

    Only ever fills a blank or relative timeframe — an explicit one was not defaulted.
    """
    try:
        plan = json.loads(plan_json or "{}")
    except (TypeError, ValueError):
        plan = {}
    if not isinstance(plan, dict):
        return plan_json
    plan["timeframe"] = str(year)
    return json.dumps(plan)


def _pin_latest_year(
    flow: str,
    scope: TurnScope,
    *,
    user_query: str,
    engine: Optional[Any] = None,
) -> TurnScope:
    """Default the scope to the latest year in the data when nothing named a period.

    Without this a bare "what is Zurich's premium in Canada?" sums EVERY year in the
    book into one number. The flows' timeframe skills have always stated the rule —
    no time reference means the latest year, never an all-years aggregate — but the
    tool path had no way to apply it: `turn_scope` reads a literal four-digit year out
    of the plan, so a blank timeframe AND a relative one ("latest year", "most
    recent") both left the scope unpinned.

    The year is read from the data via `get_latest_year`, not from a hard-coded list,
    so it stays correct as the warehouse loads forward. A turn that DOES name a
    timeframe — an explicit year, a quarter, or a multi-period term like YoY or trend
    — is left exactly as it was: those need more than one year, and pinning one would
    break them.
    """
    spec = flow_spec(flow)
    year_column = spec.date_columns.get("year")
    if not year_column or year_column in scope.filters:
        return scope
    if names_a_timeframe(user_query):
        return scope
    facts = get_latest_year(
        PrimitiveArgs(flow=flow, metric="", group_by=(), filters=dict(scope.filters)),
        engine=engine,
    )
    if not facts:
        return scope
    year = int(facts[0].value)
    logger.info("analytics scope defaulted to latest year %s (%s)", year, flow)
    return replace(scope, filters={**scope.filters, year_column: year})


def _parse_plan(plan_json: str) -> Dict[str, Any]:
    try:
        plan = json.loads(plan_json or "{}")
    except (TypeError, ValueError):
        return {}
    return plan if isinstance(plan, dict) else {}


def _as_call(call: GroundedCall) -> Dict[str, Any]:
    """A grounded call in the shape the orchestrator dispatches on."""
    return {
        "name": call.name,
        "metric": call.metric,
        "group_by": list(call.group_by),
        "filters": dict(call.filters),
        "options": dict(call.options),
    }


def _subject_from(flow: str, scope: Mapping[str, Any]) -> Optional[str]:
    """The carrier in scope — the subject a peer comparison benchmarks."""
    from core.analytics.sql import flow_spec

    column = flow_spec(flow).entity_columns.get("carrier")
    value = scope.get(column) if column else None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value) if value else None


# ── graph node (flow-parameterized, one implementation for both flows) ───────


@dataclass(frozen=True)
class FlowStateKeys:
    """The AgentState keys one flow writes. Keeps the node flow-agnostic."""

    reasoning: str
    result: str
    error: str
    overflow: str
    sql: str
    analytics: str


_STATE_KEYS: Dict[str, FlowStateKeys] = {
    "gpr": FlowStateKeys(
        reasoning="gpr_reasoning",
        result="gpr_query_result",
        error="gpr_sql_error",
        overflow="gpr_overflow",
        sql="gpr_sql_query",
        analytics="gpr_analytics",
    ),
    "survey": FlowStateKeys(
        reasoning="survey_reasoning",
        result="survey_query_result",
        error="survey_sql_error",
        overflow="survey_overflow",
        sql="survey_sql_query",
        analytics="survey_analytics",
    ),
}


def _uncovered(flow: str) -> Dict[str, Any]:
    """The 'library did not answer this' update — routes the turn to LLM-SQL.

    It CLEARS the provenance key rather than writing nothing: graph state is
    checkpointed per conversation, so a value left over from an earlier turn would
    tell this turn's router that a question it never answered was covered.
    """
    return {_STATE_KEYS[flow].analytics: None}


def run_analytics_tools(
    state: Mapping[str, Any],
    *,
    flow: str,
    runner: Optional[AnalyticsToolRunner] = None,
    engine: Optional[Any] = None,
) -> Dict[str, Any]:
    """Graph node body: compute this turn from the library, or hand it to LLM-SQL."""
    if not analytics_tools_enabled():
        return _uncovered(flow)

    keys = _STATE_KEYS[flow]
    runner = runner or AnalyticsToolRunner()
    if not runner.enabled:
        return _uncovered(flow)

    from core.agents.common.contract import resolved_filters_of
    from core.agents.common.peers import pinned_peers

    question = state["messages"][-1].content
    try:
        turn = runner.run(
            flow=flow,
            user_query=question,
            plan_json=state.get(keys.reasoning) or "",
            resolved_filters=resolved_filters_of(state.get("routing_context")),
            peers=pinned_peers(
                state.get("custom_peers"),
                flow,
                active=bool(state.get("custom_peers_active", False)),
            ),
            engine=engine,
        )
    except Exception:  # noqa: BLE001 - the SQL path is the fallback, not an error page
        logger.exception("analytics tool path failed for flow %s", flow)
        return _uncovered(flow)

    log_event(
        logger,
        "analytics_tools",
        flow=flow,
        node=f"{flow}_analytics_tools",
        calls=[call.describe() for call in turn.calls],
        rejected=list(turn.rejected),
        skipped=list(turn.skipped),
        rows=len(turn.rows),
        covered=turn.covered,
    )

    if not turn.covered:
        return _uncovered(flow)

    update = {
        keys.result: turn.rows,
        keys.error: False,
        keys.overflow: turn.overflow,
        keys.sql: turn.provenance(),
        keys.analytics: {
            "calls": [call.describe() for call in turn.calls],
            "scope": dict(turn.scope),
            "facts": facts_digest(turn.facts),
        },
    }
    if turn.defaulted_year is not None:
        # Safe on a covered turn: the SQL nodes that also read this key are the
        # fallback path, which the router skips whenever the library answered.
        update[keys.reasoning] = _plan_stating_timeframe(
            state.get(keys.reasoning) or "", turn.defaulted_year
        )
    return update


def analytics_covered(state: Mapping[str, Any], flow: str) -> bool:
    """True when `run_analytics_tools` answered the turn (used by the routers)."""
    return bool(state.get(_STATE_KEYS[flow].analytics))
