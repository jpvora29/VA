"""Status-line progress: allowlisted, business-language, never backwards.

The bug these cover: `stream_workflow` streams with `subgraphs=True`, so the
analyst solver's own `create_agent` nodes (`model`, `tools`) and its middleware
reached the status line as "Running tools" / "Running SolverObservability
Middleware".
"""
from __future__ import annotations

import pytest

from ui.progress import (
    DEFAULT_LABEL,
    PRESENT,
    RETRIEVE,
    STEPS,
    Step,
    advance,
    label_of,
    step_for,
)


# ── the leak ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "internal",
    [
        "model",
        "tools",
        "SolverObservabilityMiddleware",
        "SolverObservabilityMiddleware.after_model",
        "ModelRetryMiddleware",
        "SummarizationMiddleware",
        "__start__",
    ],
)
def test_solver_internals_never_take_over_the_status_line(internal):
    showing = STEPS["peer_solver_node"]
    assert advance(showing, internal) is showing


def test_unknown_node_before_anything_named_leaves_the_default():
    assert label_of(advance(None, "tools")) == DEFAULT_LABEL


def test_no_label_is_an_internal_name():
    """Nothing a user reads may mention a node, a class, or a middleware."""
    for step in STEPS.values():
        assert "_" not in step.label
        assert "Middleware" not in step.label
        assert not step.label.startswith("Running ")


# ── the ratchet ──────────────────────────────────────────────────────────────

def test_progress_does_not_go_backwards():
    """Parallel lenses interleave; the line must not fall back to retrieval."""
    writing = advance(None, "writer_node")
    assert advance(writing, "gpr_execute_sql") is writing


def test_same_phase_steps_still_swap():
    """Charts and prose share a phase because their order differs per path."""
    writing = STEPS["writer_node"]
    charting = advance(writing, "chart_picker_node")
    assert charting is STEPS["chart_picker_node"]
    assert charting.phase == writing.phase == PRESENT


def test_a_turn_walks_forward_through_its_phases():
    nodes = [
        "context_filler",
        "clarify_gate",
        "router",
        "planner_node",
        "schema_identifier_node",
        "peer_solver_node",
        "tools",            # solver internal — ignored
        "model",            # solver internal — ignored
        "generic_solver_node",
        "join_node",
        "writer_node",
        "chart_picker_node",
        "followup_node",
    ]
    step = None
    phases = []
    for node in nodes:
        step = advance(step, node)
        phases.append(step.phase)
    assert phases == sorted(phases)
    assert label_of(step) == "Suggesting follow-ups"


def test_gate_nodes_stay_neutral():
    """clarify_* and the classifier run on every turn and usually do nothing."""
    for node in ("clarify_decide", "clarify_gate", "intent_classifier", "custom_peer_gate"):
        assert STEPS[node].label == "Understanding your question"


def test_step_for_and_label_defaults():
    assert step_for(None) is None
    assert step_for("nope") is None
    assert label_of(None) == DEFAULT_LABEL
    assert label_of(Step(RETRIEVE, "Pulling the premium figures")) == "Pulling the premium figures"
