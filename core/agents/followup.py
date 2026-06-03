"""Follow-up suggestion node.

Terminal node of the chat workflow: every route funnels through here before
END, so it has the full turn context (question, route, final answer, SQL
evidence). Output is persisted by the checkpointer alongside the rest of the
turn state, and surfaced as clickable chips in the UI.
"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Tuple

import dspy

from core.initialization import Initialization
from core.observability import log_event
from core.schemas.followup import FollowupSignature
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


# Route-specific defaults used when the LLM is unavailable or returns nothing
# usable, so the chat always offers sensible next steps.
_FALLBACK_FOLLOWUPS = {
    "survey": [
        "How does this compare to peers?",
        "Which attributes scored the lowest?",
        "Show the trend over the last few years.",
    ],
    "premium": [
        "Break this down by product line.",
        "How does this compare to the peer average?",
        "Show the year-over-year trend.",
    ],
    "both": [
        "Where is broker perception misaligned with premium?",
        "Break this down by product line.",
        "How does this compare against peers?",
    ],
    "fallback": [
        "Show Share of Wallet by country.",
        "Compare premium against the peer average.",
        "What is the latest market composite rate change?",
    ],
}


def _route_context(state: AgentState, route: str) -> Tuple[str, str]:
    """Assemble the answer text and a compact evidence summary for the route."""
    if route == "survey":
        answer = (
            state.get("survey_response")
            or state.get("survey_data_overflow_msg")
            or ""
        )
        evidence = json.dumps(state.get("survey_query_result") or [], default=str)
    elif route == "premium":
        parts = [state.get("gpr_response") or "", state.get("gimmi_response") or ""]
        answer = "\n\n".join(part for part in parts if part)
        evidence = json.dumps(state.get("gpr_query_result") or [], default=str)
    elif route == "both":
        answer = state.get("combined_response") or state.get("combined_result") or ""
        evidence = json.dumps(
            {
                "survey": state.get("survey_query_result") or [],
                "premium": state.get("gpr_query_result") or [],
            },
            default=str,
        )
    else:
        answer = state.get("out_of_scope_answer") or ""
        evidence = ""

    return answer, evidence[:1500]


def _clean(items: Any) -> List[str]:
    """Normalize the model output into at most three clean question strings."""
    cleaned: List[str] = []
    for item in items or []:
        text = str(item).strip(" \t-•*0123456789.").strip()
        if text.endswith("?") and 8 <= len(text) <= 160 and text not in cleaned:
            cleaned.append(text)
    return cleaned[:3]


class FollowupNode(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(FollowupSignature)

    def forward(
        self, user_query: str, route: str, answer: str, evidence: str
    ) -> List[str]:
        with dspy.context(lm=Initialization.dspy_creative):
            result = self.predictor(
                user_query=user_query,
                route=route,
                answer=answer,
                evidence=evidence,
            )
        return result.followups


# Stateless module/predictor — instantiate once and reuse across turns.
_FOLLOWUP_NODE = FollowupNode()


def followup_node(state: AgentState) -> AgentState:
    """Generate up to three grounded follow-up questions for the current turn."""
    route = state.get("current_route") or "fallback"
    messages = state.get("messages") or []
    question = messages[-1].content if messages else ""
    answer, evidence = _route_context(state, route)

    # Nothing was answered (e.g., empty turn) — skip suggestions entirely.
    if not (answer or "").strip():
        return {"followup_questions": []}

    try:
        suggestions = _clean(
            _FOLLOWUP_NODE(
                user_query=question,
                route=route,
                answer=answer,
                evidence=evidence,
            )
        )
        log_event(
            logger,
            "followup_generated",
            node="followup_node",
            route=route,
            count=len(suggestions),
            used_fallback=not suggestions,
        )
        if suggestions:
            return {"followup_questions": suggestions}
    except Exception as exc:
        log_event(
            logger,
            "followup_error",
            logging.ERROR,
            node="followup_node",
            route=route,
            error=str(exc),
        )

    return {
        "followup_questions": _FALLBACK_FOLLOWUPS.get(
            route, _FALLBACK_FOLLOWUPS["fallback"]
        )
    }
