"""Sequential fan-in graph for the 'both' route: Survey → GPR → combined_insight."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from core.agents.combined.insight import combined_insight
from core.graph.gpr_subgraph import GPRSubGraph
from core.graph.survey_subgraph import SurveySubGraph
from core.state.agent_state import AgentState


class CombinerGraph:
    """
    Sequential fan-in graph for the 'both' route:
      survey sub-graph  →  gpr sub-graph  →  combined_insight
    Each sub-graph populates its own fields on AgentState; the combined insight node fuses them.
    """

    both_graph = StateGraph(AgentState)
    both_graph.add_node("survey", SurveySubGraph().SurveyAgent)
    both_graph.add_node("premium", GPRSubGraph().GPRAgent)
    both_graph.add_node("combined_insight", combined_insight)

    both_graph.add_edge(START, "survey")
    both_graph.add_edge("survey", "premium")
    both_graph.add_edge("premium", "combined_insight")
    both_graph.add_edge("combined_insight", END)

    CombinerAgent = both_graph.compile()
