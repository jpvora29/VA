"""HITL clarification — workflow-path interrupt nodes.

Two small nodes sit between the context filler and the rephraser:

  context_filler -> clarify_decide -> clarify_gate -> rephraser_agent

`clarify_decide` runs the conservative ambiguity classifier and writes a
`clarify_question` onto the state (persisted by the checkpointer). `clarify_gate`
reads it and, if present, calls LangGraph `interrupt()` with the MCQ payload —
pausing the graph until the Dash UI resumes the thread with `Command(resume=...)`.
On resume the gate folds the user's answer into the current query so the
rephraser + SQL agents act on the disambiguated question.

Splitting decide (LLM, runs once) from gate (interrupt, re-runs on resume) keeps
the classifier from re-firing on resume — the standard "deterministic code
before interrupt" pattern. The decision defaults to NOT asking; see
`core.schemas.hitl.ClarifyDecisionSignature`. Pitch builder does not wire these
nodes, so report generation never blocks.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import dspy
from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.types import interrupt
from pydantic import BaseModel

from core.data.valid_values import GetValidData
from core.observability import log_event
from core.schemas.hitl import ClarifyDecision, ClarifyDecisionSignature
from logger import get_logger

if TYPE_CHECKING:
    from core.state.agent_state import AgentState

logger = get_logger(__name__)


class ClarifyDecider(dspy.Module):
    """Conservative ambiguity classifier (ChainOfThought over the signature)."""

    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(ClarifyDecisionSignature)

    def forward(self, current_user_query, routing_context, valid_values) -> ClarifyDecision:
        result = self.predictor(
            current_user_query=current_user_query,
            routing_context=routing_context,
            valid_values=valid_values,
        )
        decision = result.clarify_decision
        if isinstance(decision, ClarifyDecision):
            return decision
        if isinstance(decision, dict):
            return ClarifyDecision(**decision)
        # Any odd shape: fail safe to NOT asking.
        return ClarifyDecision(needs_clarification=False, reason="unparsable decision")


_CLARIFY_DECIDER = ClarifyDecider()

# Public handles so the agent-path middleware (core.agents.analyst_agent) reuses
# the exact same conservative decider + valid-values grounding as this node.
clarify_decider = _CLARIFY_DECIDER


def _valid_values_snapshot() -> dict:
    """Compact valid-values bundle for grounding the ambiguity check + options."""
    survey = GetValidData.valid_values
    gpr = GetValidData.valid_values_gpr
    return {
        "carriers": survey.get("Carrier", []),
        "carrier_groups": gpr.get("Carrier_Group", []),
        "countries_gpr": gpr.get("Country", []),
        "products": gpr.get("Product_Line", []),
        "segments": gpr.get("Client_Segment", []),
        "survey_practices": survey.get("SurveyPractice", []),
    }


# Public alias for the agent-path middleware.
valid_values_snapshot = _valid_values_snapshot


def clarify_decide(state: "AgentState") -> "AgentState":
    """Decide whether to ask a clarifying question. Default: do not ask."""
    routing_context = state.get("routing_context")
    # Out-of-scope turns never clarify — they go straight to fallback.
    if routing_context is None or getattr(routing_context, "table_family", None) == "fallback":
        return {"clarify_question": None}

    question = state["messages"][-1].content
    try:
        decision = _CLARIFY_DECIDER(
            current_user_query=question,
            routing_context=routing_context,
            valid_values=_valid_values_snapshot(),
        )
    except Exception as exc:  # noqa: BLE001 - clarification is best-effort; never break the turn
        log_event(logger, "clarify_decide_error", logging.ERROR, node="clarify_decide", error=str(exc))
        return {"clarify_question": None}

    if not decision.needs_clarification or decision.question is None:
        return {"clarify_question": None}

    log_event(
        logger,
        "clarify_needed",
        node="clarify_decide",
        header=decision.question.header,
        reason=decision.reason,
    )
    return {"clarify_question": decision.question.model_dump()}


def clarify_gate(state: "AgentState") -> "AgentState":
    """Pause for the user's MCQ answer when a clarify question is pending.

    No question -> pure pass-through. Otherwise `interrupt()` surfaces the MCQ to
    the UI; on resume the chosen answer is folded into the current query.
    """
    clarify_question = state.get("clarify_question")
    if not clarify_question:
        return {}

    # Pauses here until the UI resumes the thread with Command(resume=<answer>).
    answer = interrupt(clarify_question)

    last = state["messages"][-1]
    original = last.content
    augmented = f"{original} (User clarification: {answer})"
    log_event(logger, "clarify_resumed", node="clarify_gate", answer=str(answer))
    return {
        "messages": [RemoveMessage(id=last.id), HumanMessage(content=augmented)],
        "clarification": str(answer),
        "clarify_question": None,
    }


def hitl_clarify(state: "AgentState") -> "AgentState":  # pragma: no cover - back-compat shim
    """Deprecated single-node entry point. Use clarify_decide + clarify_gate."""
    return clarify_gate(clarify_decide(state) or state)
