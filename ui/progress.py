"""Live turn progress, in the language of the person asking the question.

Two problems this module exists to solve.

**Internals used to leak.** `core.graph.main.stream_workflow` streams with
`subgraphs=True`, so it reports EVERY node the run enters — including the nodes
inside the analyst solver's `create_agent` graph (`model`, `tools`) and its
middleware. The old fallback turned any unrecognised name into
``f"Running {node}"``, which is how "Running tools" and
"Running SolverObservability Middleware" reached the status line. So the map here
is an **allowlist**: a node we have not deliberately named leaves the status line
exactly as it is.

**The status line jumped backwards.** Independent lenses fan out in parallel, so
node events arrive interleaved — the line could read "Writing the insight" and
then fall back to "Running the query". Every named step therefore carries a
`phase`, and `advance` only ever moves forward. Steps that share a phase (the
chart step runs before the writer on the deterministic rails and after it in the
analyst subgraph) are free to swap in either order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from core.charts.agent import AGENT_NAME as CHART_AGENT_NAME

# Phase ranks. The status line may move to a step in the same phase or a later
# one, never to an earlier one.
UNDERSTAND = 10
PLAN = 20
RETRIEVE = 30
PRESENT = 40   # charts and prose share a rank: their order differs per path.
FINISH = 50

# What the status line says before the first named node arrives.
DEFAULT_LABEL = "Thinking"


@dataclass(frozen=True)
class Step:
    """One named point in a turn: what to show, and how far along it is."""

    phase: int
    label: str


# Node name -> Step. Keys are graph node names (main graph and subgraphs, since
# `stream_workflow` streams both). Labels are written for an insurance analyst
# reading them, never for whoever wrote the node.
#
# Gate nodes (clarify_*, intent_classifier, custom_peer_gate) run on EVERY turn
# and are pass-throughs on most of them, so their labels stay neutral — a gate
# that usually does nothing must not announce itself as if it did. A real
# clarification surfaces as its own card, not here.
STEPS: Dict[str, Step] = {
    # ── Understanding the question ──────────────────────────────────────────
    "context_filler": Step(UNDERSTAND, "Understanding your question"),
    "clarify_decide": Step(UNDERSTAND, "Understanding your question"),
    "clarify_gate": Step(UNDERSTAND, "Understanding your question"),
    "intent_classifier": Step(UNDERSTAND, "Understanding your question"),
    "custom_peer_gate": Step(UNDERSTAND, "Understanding your question"),
    "rephraser_agent": Step(UNDERSTAND, "Reading your question"),
    "gpr_normalizer_agent": Step(UNDERSTAND, "Interpreting the question"),
    "survey_normalizer_agent": Step(UNDERSTAND, "Interpreting the question"),
    # ── Deciding what to look at ────────────────────────────────────────────
    "router": Step(PLAN, "Finding the right data"),
    "schema_identifier_node": Step(PLAN, "Grounding the question in the data"),
    "planner_node": Step(PLAN, "Planning the analysis"),
    "gpr_planner_node": Step(PLAN, "Planning the premium analysis"),
    "survey_planner": Step(PLAN, "Planning the survey analysis"),
    # ── Getting the numbers ─────────────────────────────────────────────────
    "survey_agent": Step(RETRIEVE, "Reviewing broker-survey data"),
    "gpr_agent": Step(RETRIEVE, "Reviewing premium data"),
    "combiner_agent": Step(RETRIEVE, "Combining survey and premium data"),
    "analyst_agent": Step(RETRIEVE, "Analyzing the data"),
    "gpr_convert_to_sql": Step(RETRIEVE, "Preparing the data pull"),
    "survey_convert_to_sql": Step(RETRIEVE, "Preparing the data pull"),
    "gpr_execute_sql": Step(RETRIEVE, "Pulling the premium figures"),
    "survey_execute_sql": Step(RETRIEVE, "Pulling the survey scores"),
    "gpr_sql_fixer_agent": Step(RETRIEVE, "Refining the data pull"),
    "survey_sql_fixer_agent": Step(RETRIEVE, "Refining the data pull"),
    "gpr_analytics_tools": Step(RETRIEVE, "Computing the numbers"),
    "survey_analytics_tools": Step(RETRIEVE, "Computing the numbers"),
    "gimmi_sqlagent_node": Step(RETRIEVE, "Pulling GIMMI detail"),
    "gimmi_execute_sql": Step(RETRIEVE, "Pulling GIMMI detail"),
    "gimmi_sql_fixer_agent": Step(RETRIEVE, "Refining the data pull"),
    "peer_solver_node": Step(RETRIEVE, "Benchmarking against peers"),
    "generic_solver_node": Step(RETRIEVE, "Gathering the evidence"),
    "join_node": Step(RETRIEVE, "Assembling the evidence"),
    # ── Turning it into an answer ───────────────────────────────────────────
    "premium_chart_data_creation": Step(PRESENT, f"{CHART_AGENT_NAME} is designing the chart"),
    "survey_chart_data_creation": Step(PRESENT, f"{CHART_AGENT_NAME} is designing the chart"),
    "chart_picker_node": Step(PRESENT, f"{CHART_AGENT_NAME} is designing the charts"),
    "survey_insight": Step(PRESENT, "Writing the insight"),
    "gpr_insight": Step(PRESENT, "Writing the insight"),
    "gimmi_insight": Step(PRESENT, "Writing the insight"),
    "writer_node": Step(PRESENT, "Writing the insight"),
    "fallback": Step(PRESENT, "Composing a response"),
    "survey_data_overflow": Step(PRESENT, "Preparing the data export"),
    # ── Wrapping up ─────────────────────────────────────────────────────────
    "boardroom_node": Step(FINISH, "Building the boardroom view"),
    "conversation_node": Step(FINISH, "Reviewing the conversation"),
    "followup_node": Step(FINISH, "Suggesting follow-ups"),
    "gpr_end_max_iterations": Step(FINISH, "Wrapping up"),
    "survey_end_max_iterations": Step(FINISH, "Wrapping up"),
    "gimmi_end_max_iterations": Step(FINISH, "Wrapping up"),
}


def step_for(node: Optional[str]) -> Optional[Step]:
    """The named step for a graph node, or None when the node is an internal."""
    return STEPS.get(node) if node else None


def advance(current: Optional[Step], node: Optional[str]) -> Optional[Step]:
    """The step to show after entering `node`, given what is showing now.

    Unnamed node -> `current` unchanged (an internal never takes over the line).
    A named node in an earlier phase -> `current` unchanged (no going backwards).
    Otherwise the new step, so same-phase steps still swap in arrival order.
    """
    nxt = step_for(node)
    if nxt is None:
        return current
    if current is not None and nxt.phase < current.phase:
        return current
    return nxt


def label_of(step: Optional[Step]) -> str:
    """What the status line reads — the default until a named node is entered."""
    return step.label if step is not None else DEFAULT_LABEL
