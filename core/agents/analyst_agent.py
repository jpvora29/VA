"""Bounded proactive analyst agent (hybrid rails + agent).

For interpretive / multi-step / "both" queries, this node:

  1. Asks the lens planner (`core.analysis.plan_analysis`) which complementary
     analytical lenses add value and in what order.
  2. Runs a bounded ReAct loop (`langchain.agents.create_agent`) with a
     READ-ONLY tool allowlist (all backed by `core.mcp.tools`) and a hard
     iteration cap, following the lens bodies + always-on analyst principles.
  3. Writes the synthesized answer + evidence rows into the same AgentState
     fields the UI and follow-up node already read for `current_route`, so no
     downstream node or UI code changes.

Lookups never reach here — the router keeps those on the cheap deterministic
subgraphs. The agent only ever reads data; writes/DDL are rejected server-side
by `execute_sql`.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from core.analysis import get_lens_library, plan_analysis
from core.graph.hitl import clarify_decider, valid_values_snapshot
from core.initialization import Initialization
from core.mcp.tools import (
    execute_sql,
    fix_sql,
    get_distinct_values,
    get_schema,
    get_valid_values,
    match_column_values,
)
from core.observability import latency_timer, log_event
from core.rules.gpr import GPRRules
from core.rules.survey import SurveyRules
from core.skills.loader import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)

# Legacy rule fallbacks per flow: (planner_rules, query_rules) — the exact
# bundles the deterministic subgraph nodes fall back to when no skill matches.
_LEGACY_RULES = {
    "gpr": (GPRRules.planner_rules, GPRRules.query_rules),
    "survey": (SurveyRules.planner_rules, SurveyRules.query_rules),
}

# Super-step budget for the ReAct loop. Each tool round is ~2 steps, so this
# allows roughly 9-10 tool calls before the loop is force-stopped.
_RECURSION_LIMIT = 20

# Rows returned to the model per tool call (keeps the context bounded); the full
# rows are still captured as evidence for the UI table.
_TOOL_ROW_PREVIEW = 50

# How many times run_sql will auto-repair + re-run a failing query before giving
# up. Mirrors the deterministic subgraphs' 3-attempt SQL-fixer loop so the agent
# path is just as resilient to a malformed first query.
_SQL_MAX_ATTEMPTS = 3

# Per-flow nudges handed to the SQL fixer, matching the deterministic nodes.
_FIXER_EXTRA_RULES = {
    "gpr": "- Always use the `Carrier_Group` column instead of `Carrier_Name`.",
}

# current_route -> the flow the agent should reason over by default.
_FLOW_BY_ROUTE = {"survey": "survey", "premium": "gpr", "both": "gpr"}


def _autofix_sql(flow: str, question: str, sql: str, error: str) -> str | None:
    """Best-effort repair of a failing query via the shared LLM SQL fixer.

    Returns the corrected SQL, or None if the fixer itself errors (in which case
    the caller simply re-runs the previous SQL — covering transient DB errors).
    """
    try:
        schema_tables = get_schema(flow)  # e.g. {"GPR": [...], "Peers": [...]}
        return fix_sql(
            flow,
            user_query=question,
            schema_tables=schema_tables,
            peer_schema=schema_tables.get("Peers", []),
            sql_query=sql,
            error_message=error,
            extra_rules=_FIXER_EXTRA_RULES.get(flow, ""),
        )
    except Exception as exc:  # noqa: BLE001 - never let a fix attempt crash the turn
        log_event(
            logger,
            "run_sql_autofix_error",
            logging.ERROR,
            node="analyst_agent",
            flow=flow,
            error=str(exc),
        )
        return None


def _build_tools(evidence: List[Dict[str, Any]], question: str):
    """Read-only LangChain tools for the agent; `evidence` collects executed rows."""

    @tool
    def run_sql(flow: str, sql: str) -> str:
        """Execute a single read-only SELECT and return JSON rows.

        `flow` is one of "survey", "gpr", "gimmi" (which table family to query).
        Returns a JSON object {row_count, rows}. Write/DDL statements are
        rejected. If the query fails, it is automatically repaired and re-run up
        to 3 times before any error is returned, so an "ERROR:" reply means the
        query could not be made to run — NOT that the data is missing. A
        successful reply with row_count 0 is the only signal of genuinely no data.
        """
        attempt_sql = (sql or "").strip()
        last_error = ""
        for attempt in range(1, _SQL_MAX_ATTEMPTS + 1):
            result = execute_sql(flow, attempt_sql)
            if not result.error:
                evidence.append({"flow": flow, "sql": attempt_sql, "rows": result.rows})
                return json.dumps(
                    {
                        "row_count": result.row_count,
                        "rows": result.rows[:_TOOL_ROW_PREVIEW],
                    },
                    default=str,
                )
            last_error = result.error
            log_event(
                logger,
                "run_sql_retry",
                logging.WARNING,
                node="analyst_agent",
                flow=flow,
                attempt=attempt,
                error=last_error,
            )
            if attempt < _SQL_MAX_ATTEMPTS:
                attempt_sql = _autofix_sql(flow, question, attempt_sql, last_error) or attempt_sql
        return (
            f"ERROR (failed after {_SQL_MAX_ATTEMPTS} auto-repaired attempts): "
            f"{last_error}. This is a SQL-construction problem, not missing data — "
            f"rewrite the query with a different shape and call run_sql again. Do "
            f"NOT conclude that no data exists from this error."
        )

    @tool
    def resolve_value(flow: str, column: str, term: str) -> str:
        """Fuzzy-match a loose term to the exact valid values of a column.

        Use BEFORE filtering on dimensions like SIC_Major_Class (industry),
        SIC_Minor_Class, Product_Line, Business_Line, Cover_Line, Client_Segment,
        Region, or survey Sections / Attributes. Returns a JSON list of matches.
        """
        return json.dumps(match_column_values(flow, column, term), default=str)

    @tool
    def list_values(flow: str, column: str) -> str:
        """List the distinct valid values of a column (e.g. all industries)."""
        return json.dumps(get_distinct_values(flow, column), default=str)

    @tool
    def show_valid_values(flow: str) -> str:
        """Return the precomputed valid column values for a flow."""
        return json.dumps(get_valid_values(flow), default=str)

    return [run_sql, resolve_value, list_values, show_valid_values]


def _domain_rules(route: str, primary_flow: str, trigger_text: str) -> str:
    """Domain planning + SQL-construction rules, from the SAME source the rails use.

    Uses the skill loader (scopes "planner" + "sql"), falling back to the legacy
    `core.rules.*` bundles when no skill matches — identical to the subgraph
    nodes. For a "both" route we load both flows so the agent has each family's
    rules. `trigger_text` is the question plus every derived sub-question, so a
    skill triggered by any step in the battery is included (not just the
    top-level phrasing).
    """
    loader = get_skill_loader()
    flows = ["gpr", "survey"] if route == "both" else [primary_flow]
    blocks: List[str] = []
    for flow in flows:
        if flow not in _LEGACY_RULES:  # gimmi handles its own rules elsewhere
            continue
        legacy_planner, legacy_sql = _LEGACY_RULES[flow]
        planner_rules = loader.planner(flow, trigger_text) or legacy_planner
        sql_rules = loader.sql(flow, trigger_text) or legacy_sql
        blocks.append(
            f"### {flow.upper()} — planning rules\n{planner_rules}\n\n"
            f"### {flow.upper()} — SQL construction rules\n{sql_rules}"
        )
    return "\n\n".join(blocks)


def _system_prompt(question: str, route: str, flow: str, plan) -> str:
    library = get_lens_library()
    lens_names: List[str] = []
    for derived in plan.derived:
        if derived.lens not in lens_names:
            lens_names.append(derived.lens)
    lens_bodies = library.bodies(lens_names) or "(no specific lenses selected)"

    if plan.derived:
        steps = "\n".join(
            f"{i}. [{d.lens}] {d.sub_question}"
            + (f"  (depends on step(s) {d.depends_on})" if d.depends_on else "")
            for i, d in enumerate(plan.derived)
        )
        focus = plan.synthesis_focus or "Lead with the user's literal question."
    else:
        steps = (
            "0. Answer the user's literal question.\n"
            "1. Add the most relevant context (market, trend, peer) the data supports."
        )
        focus = "Answer the question, then add the context a good analyst would."

    schema = json.dumps(get_schema(flow), default=str)

    # Enrich the skill-trigger text with every derived sub-question so skills
    # needed by any step of the analysis are matched, not just the top question.
    trigger_text = " ".join(
        [question] + [d.sub_question for d in plan.derived if d.sub_question]
    )
    domain_rules = _domain_rules(route, flow, trigger_text)

    return f"""You are a proactive insurance strategy analyst. Answer the user's
question and proactively add the context a good analyst would bring — going
beyond the literal ask where the data supports it.

[ANALYST PRINCIPLES]
{library.principles()}

[YOUR PLAN — execute these derived analyses in order, respecting dependencies]
{steps}

Synthesis focus: {focus}

[LENSES TO APPLY — follow these SQL shapes and interpretations]
{lens_bodies}

[PRIMARY FLOW] {flow}  (route="{route}"). Use run_sql with this flow for the
main analysis; for a "both" route you may also query flow="survey" for the
perception lens. The GPR table IS Marsh's book of business (the market proxy).

[SCHEMA for flow="{flow}"]
{schema}

[DOMAIN RULES — the same business + SQL-construction rules the deterministic
path uses. Follow these when building queries: Carrier_Group handling, peer
averages via the Peers table, Share-of-Wallet / appetite math, Marsh premium,
rolling-12M, ranking, confidentiality, etc.]
{domain_rules}

[RULES]
- Use run_sql for ALL data. Never state a number you did not retrieve.
- Before filtering on a dimension value (industry, product, cover line, etc.),
  call resolve_value to map the user's wording to an exact valid value.
- Keep each query focused; build dependent queries from earlier results.
- Stay within ~9 tool calls. run_sql auto-repairs and re-runs a failing query up
  to 3 times on its own; if it still returns an ERROR, the SQL was wrong — try a
  DIFFERENT query shape, never give up after one failure.
- "No data" is ONLY valid when run_sql SUCCEEDS with row_count 0. Never report
  missing/absent data on the basis of an ERROR — that means the query failed,
  not that the data is absent.
- Only assert what the evidence supports; never fabricate.

[CONFIDENTIALITY — non-negotiable]
- Peers are ALWAYS aggregated. NEVER expose an individual peer/carrier name in
  the answer. Refer to peers only in aggregate ("peer average", "the peer set",
  "vs. peers") even if a tool returned individual names. Marsh's GPR book is the
  market proxy (no carrier filter); it is fine to name Marsh.

[OUTPUT CONTRACT — your FINAL message is a single Markdown string. You are the
deeper, agentic path: deliver MORE than a templated workflow would — more
quantified findings, more cross-lens synthesis, more genuine "so what". Be
richer, not longer for its own sake.]

Structure (use `### ` H3 headings; emoji prefix optional):

1. LEAD — open with ONE H3 heading that states the headline answer in a glance.
   2-3 lines: the direct answer + headline number + business impact. You may
   title it "📌 Executive Summary", "📌 Bottom Line", "📌 TL;DR", or whatever
   fits the question — but it MUST be the first line (no preamble before it).

2. BODY — then 2-4 H3 sections whose HEADINGS YOU CHOOSE to fit THIS question.
   Do not force a fixed template. Name each section after what the data actually
   shows, e.g. "📉 Rate Adequacy Gap", "🏆 Peer Benchmarking", "🎯 Appetite
   Concentration", "🔄 Retention Risk", "📈 Trend & Momentum", "🧩 Segment Mix",
   "🔍 Why This Is Happening". Pick the lenses your plan surfaced. Each section
   is real analysis: rank shifts, SoW/appetite moves, YoY/QoQ deltas,
   peer-aggregate gaps, drivers, disconnects (e.g. premium up but SoW down =
   market grew faster). **Bold the critical numbers.** Use 📈 📉 ⚠️ ✅ where natural.

3. RECOMMENDATIONS — one H3 section, 2-4 bullets, each starting with a verb
   (Defend, Grow, Re-price, Exit, Re-underwrite, Target) tied to a finding above.

4. SUPPORTING DATA — final H3 section ("📊 Supporting Data"). ALWAYS include a
   compact Markdown table (top 5-10 rows), one row per entity/period. Format
   premium as currency (e.g. $12.4M); SoW / Appetite / YoY / QoQ as %. Aggregate
   peers into a single "Peer avg" row — never one row per named peer. If the
   answer is a single scalar, still give a small 1-2 row table for context.

STYLE: executive tone, no hedging, no filler, no data-dictionary phrasing; never
repeat the same fact across sections.

[USER QUESTION]
{question}"""


class ClarifyMiddleware(AgentMiddleware):
    """Agent-path HITL: a `before_agent` hook that asks ONE MCQ when the analytical
    query is genuinely ambiguous, mirroring the workflow-path clarify gate.

    It reuses the SAME conservative decider as `core.graph.hitl`, so behavior is
    consistent across both paths. `before_agent` runs once, at a deterministic
    position, before the ReAct loop — the safe place to `interrupt()`. The
    interrupt propagates out of this nested agent to the checkpointed main graph,
    which surfaces it to the UI and resumes the thread with the user's answer.

    Skipped entirely when the turn was already clarified upstream (the workflow
    gate ran first), so a turn is never double-asked.
    """

    def __init__(self, question: str, routing_context, already_clarified: bool) -> None:
        super().__init__()
        self._question = question
        self._routing_context = routing_context
        self._already_clarified = already_clarified

    def before_agent(self, state, runtime):  # noqa: ANN001 - langchain middleware signature
        if self._already_clarified:
            return None
        try:
            decision = clarify_decider(
                current_user_query=self._question,
                routing_context=self._routing_context,
                valid_values=valid_values_snapshot(),
            )
        except GraphInterrupt:
            raise
        except Exception:  # noqa: BLE001 - clarification is best-effort
            return None

        if not decision.needs_clarification or decision.question is None:
            return None

        # Pauses the nested agent; propagates to the checkpointed main graph.
        answer = interrupt(decision.question.model_dump())
        return {
            "messages": [HumanMessage(content=f"User clarification: {answer}")]
        }


# Module-level so the underlying model/client is reused across turns.
_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        _MODEL = Initialization.llm
    return _MODEL


def analyst_agent_node(state: AgentState) -> AgentState:
    """Plan lenses, run the bounded tool-calling loop, map results onto state."""
    route = (state.get("current_route") or "both").lower()
    flow = _FLOW_BY_ROUTE.get(route, "gpr")
    question = state["messages"][-1].content
    routing_context = state.get("routing_context")

    plan = plan_analysis(question, routing_context, mode="chat")
    log_event(
        logger,
        "analysis_planned",
        node="analyst_agent",
        route=route,
        flow=flow,
        lenses=[d.lens for d in plan.derived],
        derived_count=len(plan.derived),
    )

    evidence: List[Dict[str, Any]] = []
    tools = _build_tools(evidence, question)
    system_prompt = _system_prompt(question, route, flow, plan)
    # Agent-path HITL middleware. Skips when the workflow clarify gate already
    # disambiguated this turn (state["clarification"] set on resume).
    clarify_mw = ClarifyMiddleware(
        question=question,
        routing_context=routing_context,
        already_clarified=bool(state.get("clarification")),
    )
    agent = create_agent(
        _model(), tools, system_prompt=system_prompt, middleware=[clarify_mw]
    )

    answer = ""
    with latency_timer() as timing:
        try:
            result = agent.invoke(
                {"messages": [HumanMessage(content=question)]},
                config={"recursion_limit": _RECURSION_LIMIT},
            )
            answer = (result["messages"][-1].content or "").strip()
        except GraphInterrupt:
            # A clarify MCQ is pending — let it bubble to the checkpointed main
            # graph so the UI can ask and resume. Never swallow this as an error.
            raise
        except Exception as exc:  # noqa: BLE001 - never crash the turn
            log_event(
                logger,
                "analyst_agent_error",
                logging.ERROR,
                node="analyst_agent",
                route=route,
                error=str(exc),
            )

    log_event(
        logger,
        "analyst_agent_done",
        node="analyst_agent",
        route=route,
        tool_calls=len(evidence),
        answered=bool(answer),
        duration_ms=timing.get("duration_ms"),
    )

    if not answer:
        # Graceful fallback so the UI still renders something for the route.
        answer = (
            "I couldn't complete the analysis for this question. "
            "Please try rephrasing or narrowing it."
        )

    def _rows_for(target_flow: str) -> List[Any]:
        for item in evidence:
            if item["flow"] == target_flow and item["rows"]:
                return item["rows"]
        return []

    if route == "survey":
        return {"survey_response": answer, "survey_query_result": _rows_for("survey")}
    if route == "both":
        return {
            "combined_response": answer,
            "survey_query_result": _rows_for("survey"),
            "gpr_query_result": _rows_for("gpr"),
        }
    # premium (and any default)
    return {"gpr_response": answer, "gpr_query_result": _rows_for("gpr")}
