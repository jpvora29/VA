"""End-to-end: the analyst subgraph's evidence loop over the fixture warehouse.

Unit tests cover the pieces — identity, materiality, the contract. This walks
the real nodes in their real order with a stubbed solver, and asserts the three
behaviours that only appear once they are wired together:

  * the parallel wave's evidence is attributed to the steps that asked for it,
    so a requirement can say whether it was met;
  * a drill-down is admitted by an observed movement and aimed at the product
    that actually moved, with no drill-down when nothing did;
  * the same query arriving from two solvers, or from a retry, produces ONE
    evidence record rather than two confirmations of one number.

The solver is stubbed because the graph's solver is an LLM ReAct loop and this
environment has no credentials. Everything below the solver is real: the
contract, the planner bounds, the merge reducer, the outcome recording, the
materiality rule and the stop reason. The NUMBERS the stub returns come from the
evaluation warehouse, so what the loop reasons over is the hand-checked scenario
rather than invented rows.
"""
from __future__ import annotations

import pytest

from core.analysis.evidence_ledger import VALIDATED
from core.analysis.progress import PlanProgress
from core.graph import analyst_subgraph as subgraph
from core.schemas.analysis import AnalysisPlan, DerivedAnalysis
from core.schemas.analyst_subgraph import SchemaSlice
from tests.evaluation import oracles, scenario

SCOPE = {"Carrier_Group": scenario.CARRIER, "Country": scenario.COUNTRY}


def product_rows():
    """The product decomposition, straight from the reference calculation."""
    contributions = oracles.product_contributions()
    return [
        {
            "Product_Line": product,
            "contribution": movement.absolute,
            "contribution_pp": round(contributions[product], 1),
        }
        for product, movement in oracles.product_movements().items()
    ]


def headline_row():
    movement = oracles.headline_movement()
    return {"scope": "total", "change": movement.absolute}


def quarter_rows():
    return [
        {"period": f"Q{quarter}", "change": movement.absolute}
        for quarter, movement in oracles.quarter_movements().items()
    ]


@pytest.fixture
def state():
    plan = AnalysisPlan(
        derived=[
            DerivedAnalysis(lens="temporal_trend", sub_question="annual movement"),
            DerivedAnalysis(lens="dimensional_breakdown", sub_question="by product"),
            DerivedAnalysis(lens="temporal_trend", sub_question="by quarter",
                            depends_on=[0]),
        ],
        synthesis_focus="explain the decline",
    )
    contract = subgraph.build_contract(
        "performance_assessment",
        conditions=["material_product_movement"],
        allowed_sources=["gpr"],
    )
    plan = subgraph.assign_identity(plan, contract=contract, scope=SCOPE)
    return {
        "question": "How was Zurich's performance in Singapore in 2025?",
        "route": "premium",
        "flow": "gpr",
        "routing_context": None,
        "plan": plan,
        "contract": contract,
        "progress": PlanProgress(contract=contract),
        "schema_slice": SchemaSlice(tables=["GPR"]),
        "evidence": [],
    }


@pytest.fixture
def stub_solver(monkeypatch):
    """Replace the LLM solver with a scripted one; record what it was asked."""
    calls = []

    def _install(script):
        def fake(*, sub_question, lens, flow, **_kwargs):
            calls.append({"sub_question": sub_question, "lens": lens, "flow": flow})
            rows = script(sub_question)
            return [{"flow": flow, "lens": lens, "sql": f"-- {sub_question}", "rows": rows}]

        monkeypatch.setattr(subgraph, "solve_generic", fake)
        monkeypatch.setattr(subgraph, "solve_peer", fake)
        return calls

    return _install


def performance_script(sub_question: str):
    if "product" in sub_question:
        return [headline_row(), *product_rows()]
    if "quarter" in sub_question:
        return quarter_rows()
    if "industry" in sub_question:
        return [
            {"SIC_Major_Class": industry, "contribution": movement.absolute}
            for industry, movement in oracles.industry_movements("Property").items()
        ]
    return [headline_row()]


# --------------------------------------------------------------------------- #


def test_the_parallel_wave_is_attributed_to_the_steps_that_asked_for_it(state, stub_solver):
    stub_solver(performance_script)
    wave = []
    for send in subgraph.dispatch(state):
        wave.extend(subgraph.generic_solver_node(send.arg)["evidence"])

    assert {row["step_id"] for row in wave} == {"s0_temporal_trend", "s1_dimensional_breakdown"}
    assert all(row["evidence_id"] for row in wave)
    assert all(row["status"] == VALIDATED for row in wave)

    state["evidence"] = wave
    result = subgraph.join_node(state)
    progress = result["progress"]
    assert "annual_movement" in progress.satisfied_requirements()
    assert "product_contributors" in progress.satisfied_requirements()


def test_the_drilldown_targets_the_product_that_actually_moved(state, stub_solver):
    calls = stub_solver(performance_script)
    state["evidence"] = [
        subgraph.stamp_step(
            {"flow": "gpr", "lens": "dimensional_breakdown", "sql": "-- by product",
             "rows": [headline_row(), *product_rows()]},
            state["plan"].derived[1],
            SCOPE,
        )
    ]
    subgraph.join_node(state)

    drilldowns = [c for c in calls if "industry" in c["sub_question"]]
    assert len(drilldowns) == 1
    worst, _ = oracles.largest_negative_contributor()
    assert worst in drilldowns[0]["sub_question"]


def test_no_drilldown_when_nothing_moved_materially(state, stub_solver):
    calls = stub_solver(lambda _q: [{"scope": "total", "change": -250.0},
                                    {"Product_Line": "Property", "contribution": -0.4}])
    state["evidence"] = [
        subgraph.stamp_step(
            {"flow": "gpr", "lens": "dimensional_breakdown", "sql": "-- by product",
             "rows": [{"scope": "total", "change": -250.0},
                      {"Product_Line": "Property", "contribution": -0.4}]},
            state["plan"].derived[1],
            SCOPE,
        )
    ]
    result = subgraph.join_node(state)
    assert not [c for c in calls if "industry" in c["sub_question"]]
    assert result["progress"].stop_reason


def test_the_same_query_from_two_solvers_becomes_one_record(state, stub_solver):
    """Two lenses that happen to need the same breakdown must not double-count it."""
    stub_solver(performance_script)
    step = state["plan"].derived[1]
    raw = {"flow": "gpr", "lens": "dimensional_breakdown", "sql": "-- by product",
           "rows": product_rows()}
    left = subgraph.stamp_step(dict(raw), step, SCOPE)
    right = subgraph.stamp_step(dict(raw), state["plan"].derived[0], SCOPE)

    merged = subgraph.merge_evidence([], [left, right])
    assert len(merged) == 1


def test_an_unmet_requirement_survives_into_a_stated_limitation(state, stub_solver):
    """A quarterly step that finds nothing must produce a sentence, not silence."""
    stub_solver(lambda sub_question: [] if "quarter" in sub_question
                else [headline_row(), *product_rows()])
    state["evidence"] = [
        subgraph.stamp_step(
            {"flow": "gpr", "lens": "dimensional_breakdown", "sql": "-- by product",
             "rows": [headline_row(), *product_rows()]},
            state["plan"].derived[1],
            SCOPE,
        )
    ]
    progress = subgraph.join_node(state)["progress"]
    assert "quarterly_comparison" not in progress.satisfied_requirements()
    assert any("quarter" in text.lower() or "No rows" in text
               for text in progress.limitations())
    assert not progress.is_complete()


def test_the_loop_always_records_why_it_stopped(state, stub_solver):
    stub_solver(performance_script)
    result = subgraph.join_node(state)
    assert result["progress"].stop_reason


# --------------------------------------------------------------------------- #
# Phase 7 — the verifier node in the real graph position
# --------------------------------------------------------------------------- #


def _record(claims=(), facts=(), limitations=()):
    return {
        "version": 4,
        "content": "",
        "claims": [dict(c) for c in claims],
        "facts": [dict(f) for f in facts],
        "limitations": list(limitations),
    }


def test_the_verifier_deletes_an_overclaiming_sentence_and_keeps_the_findings(state):
    answer = (
        "Premium fell 250. The decline was caused by rate softening. Cyber grew 90."
    )
    state["answer"] = answer
    state["answer_record"] = _record()
    result = subgraph.verify_node(state)

    assert "caused by" not in result["answer"]
    assert "Premium fell 250." in result["answer"]
    assert "Cyber grew 90." in result["answer"]


def test_the_verifier_leaves_a_clean_answer_untouched(state):
    state["answer"] = "Premium fell 250 while Cyber grew 90."
    state["answer_record"] = _record()
    assert subgraph.verify_node(state) == {}


def test_a_scope_divergence_becomes_a_stated_limitation_not_a_silent_answer(state):
    """The answer is still published — it is the SILENT version that is dangerous."""
    from core.analysis.evidence_ledger import build_evidence

    state["answer"] = "Premium fell 250."
    state["answer_record"] = _record()
    state["evidence"] = [
        build_evidence(flow="gpr", rows=[{"a": 1}], tool="t",
                       requested_scope=SCOPE, actual_scope={"Carrier_Group": scenario.CARRIER})
    ]
    result = subgraph.verify_node(state)

    assert result["answer"] == "Premium fell 250."
    limitations = result["answer_record"]["limitations"]
    assert any("wider scope" in text for text in limitations)
    assert result["answer_record"]["verification"][0]["stage"] == "retrieval"


def test_the_verifier_records_the_repair_each_failure_needs(state):
    state["answer"] = "Premium fell because of rate softening."
    state["answer_record"] = _record()
    result = subgraph.verify_node(state)
    reported = result["answer_record"]["verification"]
    assert all(entry["repair"] for entry in reported)


def test_an_answer_with_no_record_is_left_alone(state):
    state["answer"] = "Premium fell 250."
    state["answer_record"] = {}
    assert subgraph.verify_node(state) == {}


# --------------------------------------------------------------------------- #
# The contract the motivating question actually produces
# --------------------------------------------------------------------------- #


def _contract_for(question, route="both", flow="gpr"):
    return subgraph.build_turn_contract(
        {"question": question, "route": route, "flow": flow, "routing_context": None}
    )


def test_the_motivating_question_asks_for_the_evidence_the_plan_names():
    contract = _contract_for("How was Zurich's performance in Singapore in 2025?")
    assert contract.intent == "performance_assessment"
    assert contract.keys() == (
        "annual_movement", "product_contributors", "quarterly_comparison",
        "positioning", "survey_movement",
    )


def test_the_industry_drilldown_waits_for_a_result_to_justify_it():
    """It is deferred at plan time and admitted later by an observed movement."""
    contract = _contract_for("How was Zurich's performance in Singapore in 2025?")
    assert not contract.requires("industry_concentration")
    assert "industry_concentration" in {r.key for r in contract.deferred}


def test_whitespace_stays_out_while_its_thresholds_are_uncalibrated():
    contract = _contract_for("How was Zurich's performance in Singapore in 2025?")
    assert "whitespace" in {r.key for r in contract.deferred}


def test_premium_only_in_the_question_overrides_the_configured_default():
    contract = _contract_for("How was Zurich's performance in Singapore? Premium only.")
    assert not contract.requires("survey_movement")
    assert contract.sources() == ("gpr",)


def test_a_premium_route_cannot_owe_a_survey_finding():
    contract = _contract_for(
        "How was Zurich's performance in Singapore in 2025?", route="premium"
    )
    assert not contract.requires("survey_movement")


def test_a_survey_route_owes_only_the_perception_assessment():
    contract = _contract_for(
        "How do brokers rate Zurich in Singapore?", route="survey", flow="survey"
    )
    assert contract.keys() == ("survey_movement",)


def test_a_lookup_is_not_inflated_into_a_performance_review():
    contract = _contract_for(
        "What was Zurich's premium in Singapore in 2025?", route="premium"
    )
    assert contract.keys() == ("direct_value",)
