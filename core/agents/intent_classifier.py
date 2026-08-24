"""Intent Classifier node — Layer 2 of the conversational-analyst architecture.

A thin pre-router node that OWNS the turn's intent: how deep the answer should go
(`analysis_depth`), how it should be presented (`output_directives`), and whether
the turn is a conversation meta-request (`conversation_intent`) rather than a new
data question.

This is a re-layering, not new behavior. These three concerns used to be bolted
onto the end of the context filler. Pulling them into their own node keeps each
layer single-responsibility (SRP):
  - context filler (Layer 1) extracts filters + inheritance and the raw turn
    `intent_type`;
  - this node (Layer 2) finalizes the intent the router (Layer 3) and analyst
    (Layer 4) act on.

Heavy table/column identification is deliberately NOT promoted here — it stays in
`schema_identifier`, which runs only on the analytical path AFTER the router, so
cheap lookup turns pay no extra cost. The directive overlay folds over the
`_DIRECTIVE_DETECTORS` tuple (OCP) instead of a branch ladder.
"""
from __future__ import annotations

from typing import List

from langchain_core.messages import HumanMessage

from core.agents.common.directives import apply_directives
from core.agents.common.meta_intent import detect_conversation_intent
from core.llm import Predictor
from core.observability import log_event
from core.schemas.routing import DepthClassifierSignature
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class DepthClassifierNode:
    """Dedicated lookup-vs-analytical classifier.

    Split out of the monolithic context-filler call so depth gets its own
    chain-of-thought step. The combined signature reliably anchored on the
    `analysis_depth` default ("lookup"); a focused predictor with crisp contrasts
    classifies far more accurately. Its output overwrites whatever the context
    filler guessed.
    """

    def __init__(self, predictor: Predictor | None = None) -> None:
        # Fast tier: a focused lookup-vs-analytical classification, reasoned
        # through so a comparison is not mistaken for a plain breakdown.
        self.predictor = predictor or Predictor(
            DepthClassifierSignature, tier="fast", reasoning=True,
            label="depth_classifier", node="intent_classifier",
        )

    def __call__(
        self, current_user_query: str, table_family: str, intent_type: str
    ) -> str:
        # HYBRID is always analytical — a narrow deterministic floor (not a broad
        # keyword regex) so we never waste an LLM call to (re)confirm it.
        if table_family == "both":
            return "analytical"
        result = self.predictor(
            current_user_query=current_user_query,
            table_family=table_family,
            intent_type=intent_type,
        )
        decision = result.depth_decision
        depth = getattr(decision, "analysis_depth", None)
        if depth not in ("lookup", "analytical"):
            # Defensive: on any odd shape prefer the safer (richer) path.
            return "analytical"
        return depth


# Stateless predictor — instantiate once and reuse across turns (default LM).
_DEPTH_CLASSIFIER_NODE = DepthClassifierNode()


class IntentClassifier:
    """LangGraph node callable. Reads the context filler's `routing_context` and
    finalizes the turn's intent: depth, presentation directives, meta-intent.

    The depth classifier is injected (DI) so tests can supply a stub instead of
    a live LLM call.
    """

    def __init__(self, *, depth_classifier: DepthClassifierNode | None = None) -> None:
        self._depth_classifier = depth_classifier or _DEPTH_CLASSIFIER_NODE

    def classify_intent(self, state: AgentState) -> AgentState:
        routing_context = state.get("routing_context")
        if routing_context is None:
            # Defensive: context_filler always runs first. With no routing_context
            # there is nothing to classify — pass through untouched rather than
            # crash the graph.
            return {}

        question = state["messages"][-1].content

        # Re-decide analysis_depth with the dedicated classifier. The combined
        # context-filler call reliably anchored on the "lookup" default, so the
        # analytical agent path almost never fired. This focused step overwrites
        # the guess. `fallback` queries keep whatever value — they never route to
        # the analyst agent anyway.
        if routing_context.table_family != "fallback":
            routing_context.analysis_depth = self._depth_classifier(
                current_user_query=question,
                table_family=routing_context.table_family,
                intent_type=routing_context.intent_type,
            )

        # Deterministic directive overlay: fold every detector over the RAW query
        # (the rephraser may strip "without a chart" later) onto output_directives,
        # overriding whatever the LLM read.
        apply_directives(question, routing_context.output_directives)

        # Conversation meta-intent overlay: "summarize our discussion", "what did
        # you recommend earlier?". Only when there IS prior conversation to talk
        # about — a first-turn meta phrase has nothing to recap, so it falls
        # through to normal routing. A hit short-circuits past SQL/analyst to the
        # transcript handler (see the conditional edge in core.graph.main).
        user_messages: List[str] = [
            msg.content for msg in state["messages"] if isinstance(msg, HumanMessage)
        ]
        if len(user_messages) > 1:
            meta = detect_conversation_intent(question)
            if meta:
                routing_context.conversation_intent = meta

        log_event(
            logger,
            "intent_classified",
            node="intent_classifier",
            table_family=routing_context.table_family,
            intent=routing_context.intent_type,
            analysis_depth=routing_context.analysis_depth,
            charts_directive=routing_context.output_directives.charts,
            presentation_directive=routing_context.output_directives.presentation,
            depth_directive=routing_context.output_directives.depth,
            charts_directive_source=routing_context.output_directives.source,
            conversation_intent=routing_context.conversation_intent,
        )

        return {"routing_context": routing_context}
