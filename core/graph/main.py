"""Top-level LangGraph workflow.

Wires the rephraser → router → {survey | gpr | combiner | fallback} agents,
plus the post-GPR conditional GIMMI branch.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from core.agents.analyst_agent import analyst_agent_node
from core.agents.context_filler import ContextFillingAgent
from core.agents.fallback import Fallback
from core.agents.followup import followup_node
from core.agents.gimmi.response import check_if_gimmi_required, gimmi_insight
from core.agents.gimmi.sql_agent import gimmi_execute_sql, gimmi_sqlagent_node
from core.agents.gpr.response import gpr_insight
from core.agents.rephraser import QueryRephraseAgent
from core.agents.router import RouterNode
from core.agents.survey.response import survey_data_overflow, survey_insight
from core.graph.combiner_subgraph import CombinerGraph
from core.graph.checkpointer import build_chat_checkpointer, checkpoint_config
from core.graph.gpr_subgraph import GPRSubGraph
from core.graph.survey_subgraph import SurveySubGraph
from core.observability import latency_timer, log_event
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


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
        self.gimmi_insight = gimmi_insight
        self.followup_node = followup_node

    def create_workflow(self):
        workflow = StateGraph(self.state_schema)

        workflow.add_node("context_filler", self.context_filler)
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
        workflow.add_node("gimmi_insight", self.gimmi_insight)
        workflow.add_node("followup_node", self.followup_node)

        workflow.add_edge(START, "context_filler")
        workflow.add_edge("context_filler", "rephraser_agent")
        workflow.add_edge("rephraser_agent", "router")

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
        workflow.add_edge("gimmi_execute_sql", "gimmi_insight")

        workflow.add_edge("survey_data_overflow", "followup_node")
        workflow.add_edge("survey_insight", "followup_node")

        workflow.add_edge("fallback", "followup_node")

        workflow.add_edge("gimmi_insight", "followup_node")

        # Single terminal node: every route produces follow-up suggestions, then ends.
        workflow.add_edge("followup_node", END)

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
        log_event(logger, "workflow_start", node="main_workflow")
        with latency_timer() as timing:
            if self._compiled_app is None:
                self._compiled_app = self.create_workflow()
            config = checkpoint_config(thread_id or self.default_thread_id)
            state = self._compiled_app.invoke(state, config=config)
        log_event(
            logger,
            "workflow_end",
            node="main_workflow",
            duration_ms=timing.get("duration_ms"),
        )
        return state
