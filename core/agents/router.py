"""Router node — DETERMINISTIC dispatch (no LLM call).

The routing decision is now made upstream by the Context Filler and lives
on `state["routing_context"].table_family`. This node just lifts that
decision into `current_route` so the downstream conditional edges in the
main graph fire without an extra ~1.5k-token LLM round trip.

Previously this was a structured-output LLM call duplicating the
table-family logic the rephraser already did implicitly. Two passes for
one decision is wasteful; with `RoutingContext` produced upstream, the
router becomes a pure function.
"""
from __future__ import annotations

from core.state.agent_state import AgentState


class RouterNode:
    """Pure-function dispatch. No LLM, no system prompt, no token cost."""

    def __init__(self) -> None:
        # Kept for back-compat with code paths that instantiate `RouterNode()`
        # — there is no internal LLM client to set up anymore.
        pass

    def router_node(self, state: AgentState):
        routing_context = state.get("routing_context")
        if routing_context is None:
            # Defensive: should never happen because the graph wires
            # context_filler -> rephraser -> router. If it does, route to
            # fallback rather than crash the workflow.
            print("Router: routing_context missing; defaulting to fallback")
            return {"current_route": "fallback"}

        table_family = routing_context.table_family
        print(f"Router (deterministic): table_family={table_family}")
        return {"current_route": table_family}

    @staticmethod
    def relevance_router(state: AgentState) -> str:
        current_route = (state.get("current_route") or "").lower()
        if current_route == "survey":
            return "survey_agent"
        elif current_route == "premium":
            return "gpr_agent"
        elif current_route == "both":
            return "combiner_agent"
        return "fallback"
