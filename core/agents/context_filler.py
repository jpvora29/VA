"""Context Filler node.

First LLM call in the graph. Produces a `RoutingContext` from the user's
current query + recent conversation history. Downstream:
- `RephraserAgentNode` uses it to rewrite the sentence with inherited filters.
- `RouterNode` reads `routing_context.table_family` to dispatch deterministically
  (no second LLM call needed).

This split — extracted from the original monolithic rephraser — exists so
each LLM has one cognitive job (CoT works better) and so the routing
decision becomes a structured artifact instead of an implicit signal hidden
in the rephrased text.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import dspy
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from core.data.general import GeneralFunctions
from core.initialization import Initialization
from core.schemas.routing import ContextFillerSignature, RoutingContext
from core.state.agent_state import AgentState


class ContextFillerNode(dspy.Module):
    """dspy module wrapping `ContextFillerSignature` with ChainOfThought."""

    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(ContextFillerSignature)

    def forward(
        self,
        static_context: str,
        current_user_query: str,
        last_user_query: str,
        conversation_history: List[str],
    ) -> RoutingContext:
        result = self.predictor(
            static_context=static_context,
            current_user_query=current_user_query,
            last_user_query=last_user_query,
            conversation_history=conversation_history,
        )
        routing = result.routing_context
        if isinstance(routing, BaseModel):
            return routing
        # Fallback: dspy returned a dict shape — coerce to the model.
        if isinstance(routing, dict):
            return RoutingContext(**routing)
        # As a last resort, surface a default "new_question" / fallback state
        # rather than blowing up the graph.
        return RoutingContext(
            table_family="fallback",
            intent_type="new_question",
            rationale=f"context_filler returned unexpected type: {type(routing)!r}",
        )


class ContextFillingAgent:
    """LangGraph node callable. Reads `state["messages"]`, returns `routing_context`."""

    history_policy_rules = """
    [HISTORY POLICY — STRICTLY DETERMINISTIC]

    P0: Always begin with the current user query.

    P1 (immediate-prior inheritance):
        - If the current query is missing any of {Carrier, Country, Year,
          Product, Metric}, FIRST look at the immediate previous query.
        - If the current query does not explicitly name a carrier, inherit the
          carrier from the previous query.
        - Inherit only filters that are valid for the family detected for the
          current query (Carriers, GPR, or both for HYBRID).
        - If no inheritance possible from P1, fall to P2.

    P2 (older-history inheritance):
        - Scan `conversation_history` newest -> oldest.
        - Inherit filters from the most recent turn whose family matches (or
          overlaps with, for HYBRID) the current family.

    TOPIC SWITCH:
        - On a clear family switch (Carriers <-> GPR, or single-lens -> HYBRID),
          inherit ONLY filters valid in the NEW family's schema. Drop the rest.
        - Set intent_type = "topic_switch".

    SELF-REFERENCE:
        - "my", "I", "me", "our" -> inherit Carrier from most recent turn.

    GOLDEN RULES:
        - NEVER invent a metric, peer, or filter not present in the current
          query and not recoverable from history.
        - For HYBRID: leave inherited_metric null. Do not force a lens.
        - First-turn queries (empty history): all inherited_* must be null.
    """

    def context_filler_agent(self, state: AgentState) -> AgentState:
        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)

        # Reconstruct user-message timeline for history slicing.
        user_messages: List[str] = [
            msg.content for msg in state["messages"] if isinstance(msg, HumanMessage)
        ]
        # `last_user_query` is the turn just before the current one. Older
        # context goes into `conversation_history`. We deliberately pass empty
        # string / empty list (NOT None) — dspy's Optional handling is
        # inconsistent across adapters.
        if len(user_messages) > 1:
            last_user_query = user_messages[-2]
            conversation_history = user_messages[:-2][-5:]
        else:
            last_user_query = ""
            conversation_history = []

        static_context = (
            f"Schemas:\n{json.dumps(schema, sort_keys=True, default=str)}\n\n"
            f"Routing + Inheritance Rules:\n{ContextFillingAgent.history_policy_rules}\n"
        )

        node = ContextFillerNode()
        routing_context = node(
            static_context=static_context,
            current_user_query=question,
            last_user_query=last_user_query,
            conversation_history=conversation_history,
        )
        Initialization.log_prompt_cache_usage(routing_context, "context_filler_agent")

        print(
            "Context Filler Output: "
            f"table_family={routing_context.table_family}, "
            f"intent={routing_context.intent_type}, "
            f"inherited_carrier={routing_context.inherited_carrier}, "
            f"inherited_country={routing_context.inherited_country}, "
            f"inherited_year={routing_context.inherited_year}"
        )

        return {"routing_context": routing_context}
