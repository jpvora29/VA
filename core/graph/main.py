"""Top-level LangGraph workflow.

Wires the rephraser → router → {survey | gpr | combiner | fallback} agents,
plus the post-GPR conditional GIMMI branch.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from core.agents.analyst_agent import analyst_agent_node
from core.agents.boardroom import boardroom_node
from core.agents.common.meta_intent import is_meta_intent
from core.agents.context_filler import ContextFillingAgent
from core.agents.intent_classifier import IntentClassifier
from core.agents.conversation import conversation_node
from core.graph.hitl import clarify_decide, clarify_gate
from core.graph.custom_peers_gate import custom_peer_gate
from core.agents.fallback import Fallback
from core.agents.followup import followup_node
from core.agents.gimmi.response import check_if_gimmi_required, gimmi_insight
from core.agents.gimmi.sql_agent import (
    gimmi_check_attempts_router,
    gimmi_end_max_iterations,
    gimmi_execute_sql,
    gimmi_execute_sql_router,
    gimmi_sql_fixer_agent,
    gimmi_sqlagent_node,
)
from core.agents.gpr.response import gpr_insight
from core.agents.rephraser import QueryRephraseAgent
from core.agents.router import RouterNode
from core.agents.survey.response import survey_data_overflow, survey_insight
from core.graph.combiner_subgraph import CombinerGraph
from core.graph.checkpointer import build_chat_checkpointer, checkpoint_config
from core.graph.gpr_subgraph import GPRSubGraph
from core.graph.survey_subgraph import SurveySubGraph
from core.observability import latency_timer, log_event, turn_context
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


def _after_intent_classifier(state: AgentState) -> str:
    """A conversation meta-request ("summarize our chat") skips the whole
    analytical pipeline — clarify, rephrase, route, SQL — for the transcript
    handler. The IntentClassifier (Layer 2) sets `conversation_intent`; every
    other turn proceeds to the normal clarify gate."""
    if is_meta_intent(state.get("routing_context")):
        return "conversation_node"
    return "clarify_decide"


class LangGraph:
    def __init__(
        self,
        *,
        state_schema: type = AgentState,
        checkpointer: Any | None = None,
        default_thread_id: str = "chat-default",
    ) -> None:
        self.state_schema = state_schema
        self.checkpointer = (
            checkpointer if checkpointer is not None else build_chat_checkpointer()
        )
        self.default_thread_id = default_thread_id
        self._compiled_app = None

        self.context_filler = ContextFillingAgent().context_filler_agent
        self.intent_classifier = IntentClassifier().classify_intent
        self.clarify_decide = clarify_decide
        self.clarify_gate = clarify_gate
        self.custom_peer_gate = custom_peer_gate
        self.rephraser_agent = QueryRephraseAgent().rephraser_agent
        self.router = RouterNode().router_node
        self.survey_agent = SurveySubGraph().SurveyAgent
        self.gpr_agent = GPRSubGraph().GPRAgent
        self.combiner_agent = CombinerGraph().CombinerAgent
        self.analyst_agent = analyst_agent_node
        self.fallback = Fallback().fallback
        self.survey_data_overflow = survey_data_overflow
        self.survey_insight = survey_insight
        self.gpr_insight = gpr_insight
        self.gimmi_sqlagent_node = gimmi_sqlagent_node
        self.gimmi_execute_sql = gimmi_execute_sql
        self.gimmi_sql_fixer_agent = gimmi_sql_fixer_agent
        self.gimmi_end_max_iterations = gimmi_end_max_iterations
        self.gimmi_insight = gimmi_insight
        self.followup_node = followup_node
        self.boardroom_node = boardroom_node
        self.conversation_node = conversation_node

    def create_workflow(self):
        workflow = StateGraph(self.state_schema)

        workflow.add_node("context_filler", self.context_filler)
        workflow.add_node("intent_classifier", self.intent_classifier)
        workflow.add_node("clarify_decide", self.clarify_decide)
        workflow.add_node("clarify_gate", self.clarify_gate)
        workflow.add_node("custom_peer_gate", self.custom_peer_gate)
        workflow.add_node("rephraser_agent", self.rephraser_agent)
        workflow.add_node("router", self.router)
        workflow.add_node("survey_agent", self.survey_agent)
        workflow.add_node("gpr_agent", self.gpr_agent)
        workflow.add_node("combiner_agent", self.combiner_agent)
        workflow.add_node("analyst_agent", self.analyst_agent)
        workflow.add_node("fallback", self.fallback)
        workflow.add_node("survey_data_overflow", self.survey_data_overflow)
        workflow.add_node("survey_insight", self.survey_insight)
        workflow.add_node("gpr_insight", self.gpr_insight)
        workflow.add_node("gimmi_sqlagent_node", self.gimmi_sqlagent_node)
        workflow.add_node("gimmi_execute_sql", self.gimmi_execute_sql)
        workflow.add_node("gimmi_sql_fixer_agent", self.gimmi_sql_fixer_agent)
        workflow.add_node("gimmi_end_max_iterations", self.gimmi_end_max_iterations)
        workflow.add_node("gimmi_insight", self.gimmi_insight)
        workflow.add_node("followup_node", self.followup_node)
        workflow.add_node("boardroom_node", self.boardroom_node)
        workflow.add_node("conversation_node", self.conversation_node)

        workflow.add_edge(START, "context_filler")
        # Layer 1 (filter extraction) -> Layer 2 (intent: depth/directives/meta).
        workflow.add_edge("context_filler", "intent_classifier")
        # Conversation meta-requests ("summarize our discussion") branch off here
        # to the transcript handler, skipping clarify/rephrase/route/SQL entirely.
        # Every other turn proceeds down the normal analytical pipeline.
        workflow.add_conditional_edges(
            "intent_classifier",
            _after_intent_classifier,
            {
                "conversation_node": "conversation_node",
                "clarify_decide": "clarify_decide",
            },
        )
        # The transcript handler writes a prose answer and ends the turn — no
        # follow-ups, no boardroom digest (a recap is neither).
        workflow.add_edge("conversation_node", END)
        # HITL clarify hook: decide (LLM, conservative) -> gate (interrupts only
        # when a genuine MCQ is pending) -> rephraser. Pass-through otherwise.
        workflow.add_edge("clarify_decide", "clarify_gate")
        workflow.add_edge("clarify_gate", "rephraser_agent")
        # Custom-peer mismatch HITL: pauses only when a pinned peer set is active
        # and the turn asks about a different carrier. Pass-through otherwise.
        workflow.add_edge("rephraser_agent", "custom_peer_gate")
        workflow.add_edge("custom_peer_gate", "router")

        # Conditional routing
        workflow.add_conditional_edges(
            "router",
            RouterNode.relevance_router,
            {
                "survey_agent": "survey_agent",
                "gpr_agent": "gpr_agent",
                "combiner_agent": "combiner_agent",
                "analyst_agent": "analyst_agent",
                "fallback": "fallback",
            },
        )

        workflow.add_edge("combiner_agent", "followup_node")
        # The analyst agent synthesizes its own answer + evidence into the
        # route's state fields, then funnels to the terminal follow-up node.
        workflow.add_edge("analyst_agent", "followup_node")

        workflow.add_conditional_edges(
            "survey_agent",
            lambda state: (
                "survey_data_overflow"
                if state.get("survey_overflow")
                else "survey_insight"
            ),
            {
                "survey_data_overflow": "survey_data_overflow",
                "survey_insight": "survey_insight",
            },
        )

        workflow.add_edge("gpr_agent", "gpr_insight")

        workflow.add_conditional_edges(
            "gpr_insight",
            check_if_gimmi_required,
            {"gimmi_sqlagent_node": "gimmi_sqlagent_node", "end": "followup_node"},
        )

        workflow.add_edge("gimmi_sqlagent_node", "gimmi_execute_sql")
        workflow.add_conditional_edges(
            "gimmi_execute_sql",
            gimmi_execute_sql_router,
            {
                "gimmi_insight": "gimmi_insight",
                "gimmi_sql_fixer_agent": "gimmi_sql_fixer_agent",
            },
        )
        workflow.add_conditional_edges(
            "gimmi_sql_fixer_agent",
            gimmi_check_attempts_router,
            {
                "gimmi_execute_sql": "gimmi_execute_sql",
                "gimmi_end_max_iterations": "gimmi_end_max_iterations",
            },
        )
        workflow.add_edge("gimmi_end_max_iterations", "gimmi_insight")

        workflow.add_edge("survey_data_overflow", "followup_node")
        workflow.add_edge("survey_insight", "followup_node")

        workflow.add_edge("fallback", "followup_node")

        workflow.add_edge("gimmi_insight", "followup_node")

        # Single terminal funnel: every route produces follow-up suggestions, then
        # the boardroom digest (a no-op unless Boardroom Mode is on), then ends.
        workflow.add_edge("followup_node", "boardroom_node")
        workflow.add_edge("boardroom_node", END)

        compile_kwargs = {}
        if self.checkpointer is not None:
            compile_kwargs["checkpointer"] = self.checkpointer

        app = workflow.compile(**compile_kwargs)

        # mermaid_code = app.get_graph().draw_mermaid()
        # print(f"Main Workflow Graph Code: {mermaid_code}")

        return app

    def trigger_workflow(
        self, state: dict[str, Any], *, thread_id: str | None = None
    ) -> dict[str, Any]:
        tid = thread_id or self.default_thread_id
        with turn_context(thread_id=tid):
            log_event(logger, "workflow_start", node="main_workflow")
            with latency_timer() as timing:
                if self._compiled_app is None:
                    self._compiled_app = self.create_workflow()
                config = checkpoint_config(tid)
                state = self._compiled_app.invoke(state, config=config)
            log_event(
                logger,
                "workflow_end",
                node="main_workflow",
                duration_ms=timing.get("duration_ms"),
            )
            return state

    def stream_workflow(
        self,
        input_obj: Any,
        *,
        thread_id: str | None = None,
        cancel: Any | None = None,
        callbacks: list | None = None,
    ):
        """Stream a turn node-by-node so the UI can show live progress.

        `input_obj` is either a fresh state dict (new turn) or a `Command`
        (resume). Yields small dicts:
          - {"node": <name>}        as each graph node STARTS, and
          - {"interrupt": <payload>} when the graph pauses at the HITL gate.

        We stream with both "updates" and "debug" modes. The node label comes
        from the "debug" channel's `task` event, which fires when a node is
        about to run — NOT from "updates", which only fires once a node has
        finished. That distinction matters for the slow `analyst_agent`: with
        completion-only events the UI would sit on the PREVIOUS node's label
        ("Routing to the right data") for the agent's entire run and never show
        it actually running. Interrupts still come through "updates" as
        `__interrupt__`.

        Cooperative cancellation: if `cancel` (a `threading.Event`) is set, the
        loop stops at the next node boundary — LangGraph cannot abort a node
        mid-flight, so a stop takes effect once the current node returns.
        """
        if self._compiled_app is None:
            self._compiled_app = self.create_workflow()
        tid = thread_id or self.default_thread_id
        config = checkpoint_config(tid)
        # Attach the per-turn callbacks (token streaming + cancel) to the run
        # config so LangChain propagates them into every nested LLM call — most
        # importantly the analyst subgraph's writer, invoked without its own
        # config and so dependent on this propagation for live tokens.
        if callbacks:
            config = {**config, "callbacks": callbacks}
        with turn_context(thread_id=tid):
            log_event(logger, "workflow_stream_start", node="main_workflow")
            for mode, chunk in self._compiled_app.stream(
                input_obj, config=config, stream_mode=["updates", "debug"]
            ):
                if cancel is not None and cancel.is_set():
                    return
                if mode == "debug":
                    # `task` fires as a node is about to execute -> live label.
                    if chunk.get("type") == "task":
                        node_name = (chunk.get("payload") or {}).get("name")
                        if node_name:
                            yield {"node": node_name}
                    continue
                # mode == "updates": only used to surface a pending HITL interrupt.
                if "__interrupt__" in chunk:
                    interrupts = chunk["__interrupt__"]
                    payload = getattr(interrupts[0], "value", {}) if interrupts else {}
                    yield {"interrupt": payload}

    def get_state_values(self, thread_id: str | None = None) -> dict[str, Any]:
        """Read the merged channel values for a thread (the full AgentState)."""
        if self._compiled_app is None:
            self._compiled_app = self.create_workflow()
        config = checkpoint_config(thread_id or self.default_thread_id)
        snapshot = self._compiled_app.get_state(config)
        return dict(snapshot.values) if snapshot and snapshot.values else {}

    def resume_workflow(
        self, value: Any, *, thread_id: str | None = None
    ) -> dict[str, Any]:
        """Resume a thread paused at the HITL clarify gate with the user's answer.

        `value` is the MCQ answer (selected option label or free-text). The thread
        must be the SAME one that produced the `__interrupt__`, so its checkpoint
        carries the pending interrupt to resume.
        """
        tid = thread_id or self.default_thread_id
        with turn_context(thread_id=tid):
            log_event(logger, "workflow_resume", node="main_workflow")
            with latency_timer() as timing:
                if self._compiled_app is None:
                    self._compiled_app = self.create_workflow()
                config = checkpoint_config(tid)
                state = self._compiled_app.invoke(Command(resume=value), config=config)
            log_event(
                logger,
                "workflow_end",
                node="main_workflow",
                duration_ms=timing.get("duration_ms"),
            )
            return state
