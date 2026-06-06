"""Boardroom digest node.

Terminal enrichment step that runs after the route's insight writer (and the
follow-up node) when Boardroom Mode is active for the turn. It reshapes the
answer the rails already produced into a structured `BoardroomDigest` that the
UI renders as an inline dashboard card.

It is a strict no-op when `boardroom_mode` is False, so it can sit on the single
terminal edge of the main graph without affecting normal turns.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import dspy

from core.initialization import Initialization
from core.observability import log_event
from core.schemas.boardroom import BoardroomSignature
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)

# Cap rows handed to the LLM so a wide result set can't blow the context window;
# the digest only needs a representative sample to format KPIs from.
_MAX_DIGEST_ROWS = 60


class BoardroomDigestModule(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(BoardroomSignature)

    def forward(
        self, user_query: str, route: str, commentary: str, sql_output: Any
    ):
        with dspy.context(lm=Initialization.dspy_creative):
            result = self.predictor(
                user_query=user_query,
                route=route,
                commentary=commentary,
                sql_output=sql_output,
            )
        return result.digest


# Stateless module — instantiate once and reuse across turns.
_BOARDROOM_MODULE = BoardroomDigestModule()


def _gather_commentary(state: AgentState) -> str:
    """Collect EVERY answer text the turn produced, labelled by lens.

    Feeding all lenses (premium + survey + combined + gimmi) — not just the first —
    gives the digest model the cross-signal context the advanced widgets need
    (e.g. premium AND broker perception for the peer-positioning matrix)."""
    parts = []
    for label, key in (
        ("Combined", "combined_response"),
        ("Premium", "gpr_response"),
        ("Broker survey", "survey_response"),
        ("GIMMI", "gimmi_response"),
        ("Answer", "out_of_scope_answer"),
    ):
        text = (state.get(key) or "").strip()
        if text:
            parts.append(f"## {label}\n{text}")
    return "\n\n".join(parts)


def _gather_rows(state: AgentState) -> Dict[str, Any]:
    """All available result sets, keyed by lens, so the model can build timelines,
    country/product maps, and premium-vs-perception positioning from real rows."""
    data: Dict[str, Any] = {}
    for label, key in (
        ("premium", "gpr_query_result"),
        ("survey", "survey_query_result"),
        ("combined", "combined_result"),
        ("gimmi", "gimmi_query_result"),
    ):
        rows = state.get(key)
        if rows:
            data[label] = list(rows)[:_MAX_DIGEST_ROWS]
    return data


def boardroom_node(state: AgentState) -> Dict[str, Any]:
    """Distil the turn's answer into a `BoardroomDigest` when boardroom mode is on.

    CRITICAL: every non-success path must explicitly return ``{"boardroom": None}``.
    The chat graph uses a persistent checkpointer that *merges* state across turns,
    so returning ``{}`` here would leave a PRIOR turn's digest in the checkpoint and
    the UI would wrongly re-render a dashboard for a plain answer.
    """
    if not state.get("boardroom_mode"):
        return {"boardroom": None}

    commentary = _gather_commentary(state)
    if not commentary:
        # Nothing was answered (e.g. a clarify-only turn) — clear any stale digest.
        return {"boardroom": None}

    user_query = state["messages"][-1].content if state.get("messages") else ""
    route = state.get("current_route") or "analyst"
    rows = _gather_rows(state)

    try:
        digest = _BOARDROOM_MODULE(
            user_query=user_query,
            route=route,
            commentary=commentary,
            sql_output=rows,
        )
        return {"boardroom": digest.model_dump()}
    except Exception as exc:  # noqa: BLE001 - never break the turn over a presentation step
        log_event(
            logger,
            "boardroom_digest_error",
            logging.ERROR,
            route=route,
            error=str(exc),
        )
        return {"boardroom": None}
