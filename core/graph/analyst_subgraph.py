"""Multi-agent analyst subgraph.

Replaces the single ReAct loop with specialized agents that hand structured
context to each other, for context isolation and reliability:

    START
      -> planner_node            (select + order analytical lenses)
      -> schema_identifier_node  (resolve the minimal grounded schema slice once)
      -> dispatch (Send fan-out) ──▶ peer_solver_node    ─┐
                                 ──▶ generic_solver_node ─┴─▶ join_node
      -> join_node               (run dependency-bound steps serially)
      -> writer_node             (single-shot synthesis -> final Markdown)
      -> END

Independent lenses (no `depends_on`) run in parallel via the LangGraph `Send`
API; each solver appends to the shared `evidence` channel through an add-reducer,
so concurrent writes merge safely. Dependency-bound steps run serially in
`join_node`, fed the evidence the parallel wave produced.
"""
from __future__ import annotations

from operator import add
from typing import List, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import Annotated, TypedDict

from core.agents.analyst.chart_picker import pick_charts
from core.agents.analyst.generic_solver import solve_generic
from core.agents.analyst.insight_writer import write_insight
from core.agents.analyst.peer_solver import solve_peer
from core.agents.analyst.schema_identifier import identify_schema
from core.agents.analyst.common import digest_evidence
from core.analysis import plan_analysis
from core.initialization import Initialization
from core.observability import log_event
from core.schemas.analysis import AnalysisPlan
from core.schemas.analyst_subgraph import Evidence, SchemaSlice
from core.schemas.routing import RoutingContext
from logger import get_logger

logger = get_logger(__name__)

# The one lens whose work routes to the peer-comparison specialist; everything
# else goes to the generic solver.
_PEER_LENS = "peer_benchmark"


class AnalystState(TypedDict):
    """Internal state for the analyst subgraph (isolated from the global AgentState)."""

    question: str
    route: str
    flow: str
    routing_context: Optional[RoutingContext]
    # Session-pinned custom peer override + per-turn switch (see AgentState).
    custom_peers: Optional[dict]
    custom_peers_active: bool
    plan: AnalysisPlan
    schema_slice: SchemaSlice
    # add-reducer so parallel solver nodes merge their evidence instead of racing.
    evidence: Annotated[List[Evidence], add]
    answer: str
    # Up to 3 chart specs picked from the gathered evidence (title/rows/chart_data).
    charts: List[dict]


def _model():
    return Initialization.llm


def planner_node(state: AnalystState) -> dict:
    """Select and order the analytical lenses for the question (existing planner)."""
    plan = plan_analysis(state["question"], state.get("routing_context"), mode="chat")
    log_event(
        logger,
        "analysis_planned",
        node="analyst_planner",
        route=state["route"],
        flow=state["flow"],
        lenses=[d.lens for d in plan.derived],
        derived_count=len(plan.derived),
    )
    return {"plan": plan}


def schema_identifier_node(state: AnalystState) -> dict:
    """Resolve the minimal grounded schema slice the solvers will share."""
    plan: AnalysisPlan = state["plan"]
    sub_questions = [d.sub_question for d in plan.derived if d.sub_question]
    schema_slice = identify_schema(
        question=state["question"],
        sub_questions=sub_questions or [state["question"]],
        flow=state["flow"],
    )
    return {"schema_slice": schema_slice}


def _independent_indices(plan: AnalysisPlan) -> List[int]:
    """Indices of derived steps with no unmet dependency (the parallel wave 1)."""
    independent = [i for i, d in enumerate(plan.derived) if not d.depends_on]
    # The planner's step 0 always answers the literal question and should lead the
    # wave even in the rare case it was (incorrectly) marked dependent.
    if plan.derived and 0 not in independent:
        independent.insert(0, 0)
    return independent


def _target_for(lens: str) -> str:
    return "peer_solver_node" if lens == _PEER_LENS else "generic_solver_node"


def _payload(state: AnalystState, sub_question: str, lens: str) -> dict:
    """Self-contained input for a solver node (Send replaces channel state)."""
    return {
        "question": state["question"],
        "sub_question": sub_question,
        "lens": lens,
        "flow": state["flow"],
        "route": state["route"],
        "schema_slice": state["schema_slice"],
        "custom_peers": state.get("custom_peers"),
        "custom_peers_active": state.get("custom_peers_active", False),
    }


def dispatch(state: AnalystState) -> List[Send]:
    """Fan out the independent lenses to their solvers in parallel via Send."""
    plan: AnalysisPlan = state["plan"]
    if not plan.derived:
        # No plan — answer the literal question with one generic solver.
        return [Send("generic_solver_node", _payload(state, state["question"], ""))]
    sends: List[Send] = []
    for i in _independent_indices(plan):
        d = plan.derived[i]
        sends.append(Send(_target_for(d.lens), _payload(state, d.sub_question, d.lens)))
    return sends


def peer_solver_node(payload: dict) -> dict:
    """Run the peer-comparison specialist on one sub-question (parallel-safe)."""
    rows = solve_peer(
        model=_model(),
        question=payload["question"],
        sub_question=payload["sub_question"],
        lens=payload["lens"],
        flow=payload["flow"],
        route=payload["route"],
        schema_slice=payload["schema_slice"],
        custom_peers=payload.get("custom_peers"),
        custom_peers_active=payload.get("custom_peers_active", False),
    )
    return {"evidence": rows}


def generic_solver_node(payload: dict) -> dict:
    """Run the generic per-lens solver on one sub-question (parallel-safe)."""
    rows = solve_generic(
        model=_model(),
        question=payload["question"],
        sub_question=payload["sub_question"],
        lens=payload["lens"],
        flow=payload["flow"],
        route=payload["route"],
        schema_slice=payload["schema_slice"],
        custom_peers=payload.get("custom_peers"),
        custom_peers_active=payload.get("custom_peers_active", False),
    )
    return {"evidence": rows}


def join_node(state: AnalystState) -> dict:
    """Run dependency-bound steps serially, fed the parallel wave's evidence."""
    plan: AnalysisPlan = state["plan"]
    independent = set(_independent_indices(plan))
    dependent = [i for i in range(len(plan.derived)) if i not in independent]
    if not dependent:
        return {}

    accumulated: List[Evidence] = list(state.get("evidence", []))
    new_rows: List[Evidence] = []
    for i in dependent:
        d = plan.derived[i]
        solver = solve_peer if d.lens == _PEER_LENS else solve_generic
        rows = solver(
            model=_model(),
            question=state["question"],
            sub_question=d.sub_question,
            lens=d.lens,
            flow=state["flow"],
            route=state["route"],
            schema_slice=state["schema_slice"],
            prior_digest=digest_evidence(accumulated),
            custom_peers=state.get("custom_peers"),
            custom_peers_active=state.get("custom_peers_active", False),
        )
        accumulated.extend(rows)
        new_rows.extend(rows)
    return {"evidence": new_rows}


def writer_node(state: AnalystState) -> dict:
    """Synthesize the final Markdown answer from all gathered evidence."""
    plan: AnalysisPlan = state.get("plan") or AnalysisPlan()
    answer = write_insight(
        question=state["question"],
        route=state["route"],
        synthesis_focus=plan.synthesis_focus,
        evidence=list(state.get("evidence", [])),
    )
    return {"answer": answer}


def chart_picker_node(state: AnalystState) -> dict:
    """Pick and build up to 3 charts from the gathered evidence (best-effort)."""
    charts = pick_charts(state["question"], list(state.get("evidence", [])))
    log_event(
        logger,
        "analyst_charts_done",
        node="analyst_chart_picker",
        route=state["route"],
        chart_count=len(charts),
    )
    return {"charts": charts}


def build_analyst_subgraph():
    """Compile the analyst subgraph (no checkpointer — runs inside the main graph)."""
    graph = StateGraph(AnalystState)

    graph.add_node("planner_node", planner_node)
    graph.add_node("schema_identifier_node", schema_identifier_node)
    graph.add_node("peer_solver_node", peer_solver_node)
    graph.add_node("generic_solver_node", generic_solver_node)
    graph.add_node("join_node", join_node)
    graph.add_node("writer_node", writer_node)
    graph.add_node("chart_picker_node", chart_picker_node)

    graph.add_edge(START, "planner_node")
    graph.add_edge("planner_node", "schema_identifier_node")
    graph.add_conditional_edges(
        "schema_identifier_node",
        dispatch,
        ["peer_solver_node", "generic_solver_node"],
    )
    graph.add_edge("peer_solver_node", "join_node")
    graph.add_edge("generic_solver_node", "join_node")
    graph.add_edge("join_node", "writer_node")
    graph.add_edge("writer_node", "chart_picker_node")
    graph.add_edge("chart_picker_node", END)

    return graph.compile()


class AnalystSubGraph:
    """Lazily-compiled singleton wrapper, mirroring the other subgraph classes."""

    _compiled = None

    @property
    def AnalystAgent(self):
        if AnalystSubGraph._compiled is None:
            AnalystSubGraph._compiled = build_analyst_subgraph()
        return AnalystSubGraph._compiled
