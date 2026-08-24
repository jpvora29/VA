"""Context Filler node — Layer 1 (Filter Extraction).

First LLM call in the graph. Produces a `RoutingContext` from the user's current
query + recent conversation history: the SQL `table_family`, inherited filters,
the raw turn `intent_type`, and the entity mentions resolved into exact stored
values (`resolved_filters`, `query_intent`). Downstream:
- The `IntentClassifier` (Layer 2) finalizes depth/directives/meta-intent.
- `RephraserAgentNode` rewrites the sentence with inherited filters.
- `RouterNode` reads `routing_context.table_family` to dispatch deterministically
  (no second LLM call needed).

This split — extracted from the original monolithic rephraser — exists so each
LLM has one cognitive job (CoT works better) and so the routing decision becomes
a structured artifact instead of an implicit signal hidden in the rephrased text.
"""
from __future__ import annotations

import json
from typing import List

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from core.agents.common.contract import detect_metrics, resolve_entities
from core.agents.common.dimensions import detect_group_by
from core.context.bundle import schema_outline
from core.context.engine import engine_enabled
from core.data.general import GeneralFunctions
from core.initialization import Initialization
from core.llm import Predictor
from core.observability import log_event
from core.schemas.routing import (
    ContextFillerSignature,
    QueryIntent,
    RoutingContext,
)
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class ContextFillerNode:
    """Runs `ContextFillerSignature` with chain-of-thought.

    Routing and inheritance are a judgement call across the query and the history,
    so the model reasons before it answers; the reasoning stays in the prediction
    and only the typed `RoutingContext` leaves this node.
    """

    def __init__(self, predictor: Predictor | None = None) -> None:
        self.predictor = predictor or Predictor(
            ContextFillerSignature, tier="balanced", reasoning=True,
            label="context_filler_agent", node="context_filler",
        )

    def __call__(
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
        # Fallback: the model answered with a dict shape — coerce to the model.
        if isinstance(routing, dict):
            return RoutingContext(**routing)
        # As a last resort, surface a default "new_question" / fallback state
        # rather than blowing up the graph.
        return RoutingContext(
            table_family="fallback",
            intent_type="new_question",
            rationale=f"context_filler returned unexpected type: {type(routing)!r}",
        )


# Stateless module — instantiate once and reuse across turns (default LM).
# Depth/directive/meta-intent finalization now lives in the IntentClassifier
# (Layer 2); this node owns Layer 1 filter extraction only.
_CONTEXT_FILLER_NODE = ContextFillerNode()


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
        # string / empty list (NOT None) so the prompt shows an empty turn rather
        # than the renderer's "(not provided)" placeholder.
        if len(user_messages) > 1:
            last_user_query = user_messages[-2]
            conversation_history = user_messages[:-2][-5:]
        else:
            last_user_query = ""
            conversation_history = []

        # ContextEngine routing view (step 4): routing only needs to know which
        # columns live in which table to pick a table_family — not the full
        # per-column metadata. When the engine is enabled, send the compact
        # name-only outline (across all flows, since the flow isn't chosen yet).
        # Default off -> the legacy full-metadata dump, byte-identical.
        if engine_enabled():
            schema_repr = json.dumps(schema_outline(schema), sort_keys=True)
        else:
            schema_repr = json.dumps(schema, sort_keys=True, default=str)
        static_context = (
            f"Schemas:\n{schema_repr}\n\n"
            f"Routing + Inheritance Rules:\n{ContextFillingAgent.history_policy_rules}\n"
        )

        routing_context = _CONTEXT_FILLER_NODE(
            static_context=static_context,
            current_user_query=question,
            last_user_query=last_user_query,
            conversation_history=conversation_history,
        )

        # NOTE: analysis_depth, output_directives, and conversation_intent are
        # finalized downstream by the IntentClassifier (Layer 2) — this node owns
        # Layer 1 filter extraction only. The LLM's first-pass values for those
        # fields stay on routing_context until the classifier overwrites them.

        # Role detection (slice 3): grouping axes ("across industries", "by
        # product") are NOT filters. Detect them deterministically first so the
        # resolver can skip a grouping noun instead of mis-matching it to a
        # stored value (or, with semantic on, mapping "industries" onto SIC).
        group_by = detect_group_by(question, routing_context.table_family)

        # Contract resolution: turn the extracted entity MENTIONS into exact
        # stored values, once, deterministically (rapidfuzz — no LLM call).
        # Downstream the rephraser materialises these canonical names into the
        # rephrased sentence and the analyst's schema identifier seeds its
        # grounded slice with them, so every path filters on the SAME values.
        # Overwritten unconditionally — the LLM is told to leave these empty,
        # but a hallucinated value must never survive into the contract.
        routing_context.resolved_filters, routing_context.unresolved_terms = (
            resolve_entities(
                routing_context.entities,
                routing_context.table_family,
                group_by_columns=group_by.columns,
                dimension_terms=group_by.dimension_terms,
            )
        )
        routing_context.query_intent = QueryIntent(
            filters=routing_context.resolved_filters,
            group_by=group_by.columns,
            metrics=detect_metrics(question, routing_context.table_family),
        )

        log_event(
            logger,
            "context_filled",
            node="context_filler",
            table_family=routing_context.table_family,
            intent=routing_context.intent_type,
            inherited_carrier=routing_context.inherited_carrier,
            inherited_country=routing_context.inherited_country,
            inherited_year=routing_context.inherited_year,
            resolved_filter_columns=list(routing_context.resolved_filters),
            group_by=routing_context.query_intent.group_by,
            metrics=routing_context.query_intent.metrics,
            unresolved_terms=[
                f"{u.kind}:{u.term}" for u in routing_context.unresolved_terms
            ],
        )

        return {"routing_context": routing_context}
