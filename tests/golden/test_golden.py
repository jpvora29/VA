"""Step-2 golden harness tests.

Two layers:
- **Credential-free** (always run): the diff logic, harness pure helpers, the
  YAML case set, and the observability turn-sink that feeds token totals.
- **Live** (skipped without Azure creds): run the golden set through the graph,
  record a baseline on first run (or `GOLDEN_UPDATE=1`), and on later runs assert
  the candidate shows **no behavior change** vs the baseline.

Run:  pytest tests/golden -q
"""
from __future__ import annotations

import json
import os

import pytest

from tests.golden import diff as golden_diff
from tests.golden import harness
from tests.golden.harness import GoldenTrace


# ── Credential-free: diff logic ──────────────────────────────────────────────

def test_identical_traces_have_no_change():
    t = GoldenTrace(id="x", query="q", route="gpr", depth="lookup",
                    selected_skills=["a", "b"], token_total=100)
    d = golden_diff.diff_traces(t, t)
    assert not d.has_behavior_change()
    assert d.token_delta == 0


def test_route_change_is_behavior_change():
    base = GoldenTrace(id="x", query="q", route="gpr")
    cand = GoldenTrace(id="x", query="q", route="survey")
    d = golden_diff.diff_traces(base, cand)
    assert d.has_behavior_change()
    assert d.route_changed == ("gpr", "survey")


def test_skill_set_delta():
    base = GoldenTrace(id="x", query="q", selected_skills=["a", "b"])
    cand = GoldenTrace(id="x", query="q", selected_skills=["b", "c"])
    d = golden_diff.diff_traces(base, cand)
    assert d.skills_added == ["c"]
    assert d.skills_removed == ["a"]
    assert d.has_behavior_change()


def test_token_drop_is_not_a_behavior_change():
    """The whole point: smaller prompts must NOT trip the parity gate."""
    base = GoldenTrace(id="x", query="q", route="gpr", token_total=1000)
    cand = GoldenTrace(id="x", query="q", route="gpr", token_total=600)
    d = golden_diff.diff_traces(base, cand)
    assert not d.has_behavior_change()
    assert d.token_delta == -400
    assert d.token_pct == pytest.approx(-40.0)


def test_entities_change_detected():
    base = GoldenTrace(id="x", query="q", resolved_entities={"carrier": "Zurich"})
    cand = GoldenTrace(id="x", query="q", resolved_entities={"carrier": "AIG"})
    d = golden_diff.diff_traces(base, cand)
    assert d.entities_changed == {"carrier": ("Zurich", "AIG")}


def test_diff_sets_flags_missing_candidate():
    base = [GoldenTrace(id="a", query="q"), GoldenTrace(id="b", query="q")]
    cand = [GoldenTrace(id="a", query="q")]
    diffs = {d.id: d for d in golden_diff.diff_sets(base, cand)}
    assert diffs["b"].error_changed == (None, "MISSING")
    assert not diffs["a"].has_behavior_change()


# ── Credential-free: harness helpers ─────────────────────────────────────────

def test_chart_signature_dict_and_object():
    spec = harness._chart_signature(
        {"chart_type": "bar", "x": "Year", "y": ["Premium"], "series": []}
    )
    assert spec == {"type": "bar", "x": "Year", "y": ["Premium"], "series": []}
    assert harness._chart_signature({}) is None
    assert harness._chart_signature(None) is None


def test_trace_roundtrip():
    t = GoldenTrace(id="x", query="q", route="gpr", token_by_agent={"planner": 50})
    assert GoldenTrace.from_dict(t.to_dict()) == t


def test_cases_load_and_are_well_formed():
    cases = harness.load_cases()
    assert 15 <= len(cases) <= 25
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate golden ids"
    for c in cases:
        assert c.get("query"), f"{c['id']} missing query"
        assert "expected_route" in c, f"{c['id']} missing expected_route"


# ── Credential-free: observability turn-sink (feeds token totals) ─────────────

def test_turn_sink_receives_token_snapshot():
    from core.observability import (
        record_token_usage,
        reset_turn_sink,
        set_turn_sink,
        turn_context,
    )

    received: list = []
    token = set_turn_sink(lambda payload: received.append(payload))
    try:
        with turn_context(thread_id="t1"):
            record_token_usage(
                {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                label="planner",
            )
    finally:
        reset_turn_sink(token)

    assert len(received) == 1
    payload = received[0]
    assert payload["fields"].get("thread_id") == "t1"
    assert payload["token"]["total"]["total_tokens"] == 15
    assert payload["token"]["by_agent"]["planner"]["total_tokens"] == 15


def test_turn_sink_failure_never_breaks_turn():
    from core.observability import reset_turn_sink, set_turn_sink, turn_context

    def boom(_payload):
        raise RuntimeError("sink exploded")

    token = set_turn_sink(boom)
    try:
        with turn_context(thread_id="t2"):  # must not raise
            pass
    finally:
        reset_turn_sink(token)


# ── Live: shadow snapshot (skipped without creds) ────────────────────────────

requires_live = pytest.mark.skipif(
    not harness.live_available(),
    reason="needs Azure OpenAI creds (API_KEY/ENDPOINT/DEPLOYMENT) for a live graph run",
)


@requires_live
def test_golden_set_matches_baseline():
    traces = harness.run_golden_set()
    harness.BASELINE_DIR.mkdir(exist_ok=True)
    baseline_path = harness.BASELINE_DIR / "traces.json"

    if os.getenv("GOLDEN_UPDATE") == "1" or not baseline_path.exists():
        baseline_path.write_text(
            json.dumps([t.to_dict() for t in traces], indent=2), encoding="utf-8"
        )
        pytest.skip("baseline recorded — re-run to compare against it")

    baseline = [GoldenTrace.from_dict(d) for d in json.loads(baseline_path.read_text())]
    diffs = golden_diff.diff_sets(baseline, traces)
    changed = [d.summary() for d in diffs if d.has_behavior_change()]
    assert not changed, "behavior changed vs baseline:\n" + "\n".join(changed)
