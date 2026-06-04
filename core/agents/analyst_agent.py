"""Proactive analyst node — thin entry point over the multi-agent subgraph.

For interpretive / multi-step / "both" queries the router sends here. Instead of
one monolithic ReAct loop, this node invokes `core.graph.analyst_subgraph`, a
small multi-agent system with context isolation:

  1. PLANNER picks and orders the analytical lenses.
  2. SCHEMA-IDENTIFIER resolves the minimal grounded schema slice once.
  3. SOLVERS (a peer-comparison specialist + generic per-lens solvers) gather
     evidence — independent lenses run in parallel, dependency-bound ones serially.
  4. INSIGHT-WRITER synthesizes the final Markdown answer from all evidence.

This node only adapts the global `AgentState` to the subgraph and maps the result
back onto the same fields the UI and follow-up node already read for
`current_route`, so no downstream node or UI code changes. Lookups never reach
here — the router keeps those on the cheap deterministic subgraphs. The agents
only ever read data; writes/DDL are rejected server-side by `execute_sql`.
"""
from __future__ import annotations

import logging
from typing import Any, List

from langgraph.errors import GraphInterrupt

from core.graph.analyst_subgraph import AnalystSubGraph
from core.observability import latency_timer, log_event
from core.schemas.analyst_subgraph import Evidence
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)

# current_route -> the flow the agent should reason over by default.
_FLOW_BY_ROUTE = {"survey": "survey", "premium": "gpr", "both": "gpr"}

# Lazily-compiled subgraph singleton, reused across turns.
_subgraph = AnalystSubGraph()


def analyst_agent_node(state: AgentState) -> AgentState:
    """Run the analyst subgraph and map its result onto the route's state fields."""
    route = (state.get("current_route") or "both").lower()
    flow = _FLOW_BY_ROUTE.get(route, "gpr")
    question = state["messages"][-1].content

    subgraph_input = {
        "question": question,
        "route": route,
        "flow": flow,
        "routing_context": state.get("routing_context"),
        "evidence": [],
    }

    answer = ""
    evidence: List[Evidence] = []
    with latency_timer() as timing:
        try:
            # HITL clarification happens upstream in the checkpointed main graph
            # (core.graph.hitl), the only place an interrupt() can be resumed. By
            # the time we reach here the query is already disambiguated.
            result = _subgraph.AnalystAgent.invoke(subgraph_input)
            answer = (result.get("answer") or "").strip()
            evidence = result.get("evidence") or []
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
