"""Query rephraser node — SIMPLIFIED.

The original rephraser was doing three jobs at once: context inheritance,
table-family detection, and grammar/synonym normalisation. Those were split:
- Context Filler (upstream) now produces a structured `RoutingContext`.
- Router (downstream) reads RoutingContext.table_family deterministically.
- THIS node has ONE job: assemble `current_user_query` + RoutingContext
  into a single self-contained natural-language sentence the SQL agents
  can plan against.

CoT is sharper when scoped to one task; routing becomes an observable
artifact instead of an implicit signal hidden in the rephrased text.
"""
from __future__ import annotations

import dspy
from langchain_core.messages import HumanMessage, RemoveMessage

from core.initialization import Initialization
from core.schemas.routing import RephaserNodeSignature, RoutingContext
from core.state.agent_state import AgentState


class RephraserAgentNode(dspy.Module):
    """dspy module wrapping `RephaserNodeSignature` with ChainOfThought."""

    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(RephaserNodeSignature)

    def forward(
        self,
        routing_context: RoutingContext,
        construction_rules: str,
        current_user_query: str,
    ) -> str:
        result = self.predictor(
            routing_context=routing_context,
            construction_rules=construction_rules,
            current_user_query=current_user_query,
        )
        print(f"Rephrased User Query: {result.rephrased_query}")
        return result.rephrased_query


class QueryRephraseAgent:
    """LangGraph node callable. Reads `routing_context` from state and rewrites the message."""

    construction_rules = """
    - Fix grammar and expand shorthand.
    - Keep user intent intact; do not add new constraints not present in either
      the current query or the provided RoutingContext.
    - Materialise inherited filters from RoutingContext into the rephrased
      sentence so it stands alone:
          last_user_query: "Carrier A score in Singapore for the year 2025."
          current_user_query: "Its peers."
          rephrased_query: "Carrier A and its peers' score in Singapore for the year 2025."
    - If RoutingContext.timeframe_hint is set, materialise it ("last year"
      -> "2024" if the hint says so).
    - **If the user query contains phrases like across, by, keep that phrase
      intact** — the dimension mentioned (product, industry, etc.) becomes
      the downstream GROUP BY.
    - Do not generate SQL here. Return only the final rewritten natural
      language query.
    - If the latest query is already perfect and RoutingContext requires no
      inheritance, return it unchanged.
    - On topic switch (RoutingContext.intent_type == "topic_switch"), drop
      inherited filters not valid in the new family's schema.
        Example:
            last_user_query: "Zurich share in marsh book."
            current_user_query: "score"
            rephrased_query: "What is Zurich score?"
    - Do not hallucinate or invent filters absent from current query and
      RoutingContext.
    """

    def rephraser_agent(self, state: AgentState) -> AgentState:
        question = state["messages"][-1].content
        routing_context = state["routing_context"]

        node = RephraserAgentNode()
        rephrased_output = node(
            routing_context=routing_context,
            construction_rules=QueryRephraseAgent.construction_rules,
            current_user_query=question,
        )
        Initialization.log_prompt_cache_usage(rephrased_output, "rephraser_agent")

        last_msg = state["messages"][-1]
        print(f"Original User Question: {question}")

        return {
            "messages": [
                RemoveMessage(id=last_msg.id),
                HumanMessage(content=rephrased_output),
            ],
            "rephrased_user_query": rephrased_output,
        }
