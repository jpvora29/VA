"""Phases 2 and 4: evidence identity, and planning driven by results.

Two failure modes dominate these tests.

The first is duplicate evidence. A parallel fan-out and a retry both produce the
same record twice, and a second copy of a number reads downstream as a second
confirmation of it. Identity, not arrival order, has to decide.

The second is a plan that follows the question instead of the data. An industry
drill-down admitted because the user said "industry", or a percentage spike on a
three-dollar base outranking a genuine driver, are both plans that ignore what
was actually retrieved.
"""
from __future__ import annotations

import pytest

from core.analysis import build_contract
from core.analysis.evidence_ledger import (
    FAILED,
    NO_DATA,
    VALIDATED,
    build_evidence,
    evidence_id,
    identity_of,
    merge_evidence,
    quotable,
    revise,
    scope_divergence,
    supersedes,
)
from core.analysis.observations import finding_from_row, headline_from_rows, observe
from core.analysis.progress import (
    Budget,
    Finding,
    PlanProgress,
    StepOutcome,
    assign_identity,
    decide_next_steps,
    material_findings,
    stop_reason,
)
from core.analysis.validation import MAX_CHAT_LENSES, MAX_PLAN_STEPS, plan_limit, validate_plan
from core.schemas.analysis import AnalysisPlan, DerivedAnalysis

SCOPE = {"Carrier_Group": "ZURICH GROUP", "Country": "Singapore"}


def _evidence(**overrides):
    base = dict(
        flow="gpr",
        rows=[{"Product_Line": "Property", "2024": 1200.0, "2025": 900.0}],
        tool="compute_metric",
        parameters={"name": "compute_contribution", "group_by": ["Product_Line"]},
        requested_scope=SCOPE,
    )
    base.update(overrides)
    return build_evidence(**base)


# --------------------------------------------------------------------------- #
# Phase 2 — evidence identity
# --------------------------------------------------------------------------- #


def test_identity_ignores_rows_timestamp_and_asking_step():
    """The same query is the same evidence however often and by whoever it runs."""
    first = _evidence(step_id="s0_trend")
    second = _evidence(step_id="s3_breakdown", rows=[{"other": 1}])
    assert first["evidence_id"] == second["evidence_id"]


def test_identity_changes_when_the_executed_scope_changes():
    narrow = _evidence(actual_scope={**SCOPE, "Product_Line": "Property"})
    assert narrow["evidence_id"] != _evidence()["evidence_id"]


def test_whitespace_in_generated_sql_does_not_mint_a_new_record():
    a = evidence_id(flow="gpr", tool="run_sql", sql="SELECT  1   FROM GPR")
    b = evidence_id(flow="gpr", tool="run_sql", sql="SELECT 1 FROM GPR")
    assert a == b


def test_filter_ordering_does_not_change_identity():
    forward = evidence_id(flow="gpr", tool="t", actual_scope={"a": 1, "b": 2})
    reverse = evidence_id(flow="gpr", tool="t", actual_scope={"b": 2, "a": 1})
    assert forward == reverse


def test_merging_the_same_record_twice_is_a_no_op():
    record = _evidence()
    assert len(merge_evidence([record], [record])) == 1


def test_parallel_solvers_running_the_same_query_produce_one_record():
    left, right = _evidence(step_id="s1"), _evidence(step_id="s2")
    assert len(merge_evidence([], [left, right])) == 1


def test_distinct_queries_are_both_kept_in_first_seen_order():
    products = _evidence(parameters={"group_by": ["Product_Line"]})
    quarters = _evidence(parameters={"group_by": ["Quarter"]})
    merged = merge_evidence([products], [quarters])
    assert [r["evidence_id"] for r in merged] == [
        products["evidence_id"], quarters["evidence_id"]
    ]


def test_a_repair_replaces_its_predecessor_in_place():
    """A repaired number must not reshuffle the evidence an answer was built on."""
    first = _evidence(parameters={"group_by": ["A"]})
    second = _evidence(parameters={"group_by": ["B"]})
    fixed = revise(first, rows=[{"fixed": True}])
    merged = merge_evidence([first, second], [fixed])
    assert len(merged) == 2
    assert merged[0]["rows"] == [{"fixed": True}]
    assert merged[0]["version"] == 2


def test_an_older_version_cannot_overwrite_a_newer_one():
    first = _evidence()
    newer = revise(first, rows=[{"newer": True}])
    merged = merge_evidence([newer], [first])
    assert merged[0]["version"] == 2


def test_a_validated_result_replaces_a_failure_at_the_same_version():
    failure = _evidence(rows=[], status=FAILED, note="timeout")
    success = _evidence()
    assert supersedes(success, failure)
    assert not supersedes(failure, success)


def test_a_record_written_before_the_contract_still_merges():
    """No migration: a legacy dict derives the same id the builder would have."""
    legacy = {"flow": "gpr", "sql": "SELECT 1", "rows": [{"a": 1}], "lens": "trend"}
    assert identity_of(legacy) == evidence_id(flow="gpr", tool="", sql="SELECT 1")
    assert len(merge_evidence([legacy], [legacy])) == 1


def test_no_data_is_recorded_as_an_outcome_not_an_error():
    record = _evidence(rows=[])
    assert record["status"] == NO_DATA
    assert record not in quotable([record])


def test_only_validated_rows_may_be_quoted():
    good, empty = _evidence(), _evidence(parameters={"x": 1}, rows=[])
    broken = _evidence(parameters={"y": 1}, rows=[{"a": 1}], status=FAILED)
    assert quotable([good, empty, broken]) == [good]


def test_a_record_with_no_status_is_judged_by_its_rows():
    assert quotable([{"rows": [{"a": 1}], "flow": "gpr"}])
    assert not quotable([{"rows": [], "flow": "gpr"}])


def test_requested_and_executed_scope_are_kept_apart():
    """One field for both is what lets a dropped filter go undetected."""
    leaked = _evidence(actual_scope={"Carrier_Group": "ZURICH GROUP"})
    assert scope_divergence(leaked) == {"Country": "Singapore"}
    assert scope_divergence(_evidence()) == {}


def test_execution_time_is_not_presented_as_a_data_timestamp():
    record = _evidence()
    assert record["retrieved_at"]
    assert "source_version" not in record


# --------------------------------------------------------------------------- #
# Phase 4 — the plan cap
# --------------------------------------------------------------------------- #


def test_the_default_cap_admits_a_full_performance_contract():
    contract = build_contract(
        "performance_assessment",
        conditions=["material_product_movement", "comparable_survey_data"],
    )
    # movement, contributors, quarters, position, industry drill-down, survey.
    assert len(contract.selected) == 6
    assert plan_limit(contract) >= len(contract.selected)


def test_the_cap_is_no_longer_below_the_floor_a_performance_answer_needs():
    assert MAX_CHAT_LENSES >= 5


def test_a_contract_cannot_push_past_the_hard_ceiling():
    class Huge:
        selected = tuple(range(50))

    assert plan_limit(Huge()) == MAX_PLAN_STEPS


def test_a_small_contract_still_gets_the_default_headroom():
    assert plan_limit(build_contract("lookup")) == MAX_CHAT_LENSES


def test_validate_plan_still_renumbers_dependencies_when_steps_are_dropped():
    plan = AnalysisPlan(derived=[
        DerivedAnalysis(lens="unknown", sub_question="a"),
        DerivedAnalysis(lens="trend", sub_question="b"),
        DerivedAnalysis(lens="mix", sub_question="c", depends_on=[1]),
    ])
    checked = validate_plan(plan, {"trend", "mix"})
    assert [s.lens for s in checked.derived] == ["trend", "mix"]
    assert checked.derived[1].depends_on == [0]


# --------------------------------------------------------------------------- #
# Phase 4 — step identity and outcomes
# --------------------------------------------------------------------------- #


def test_every_step_gets_a_stable_id_and_its_requirement():
    contract = build_contract("performance_assessment")
    plan = assign_identity(
        AnalysisPlan(derived=[
            DerivedAnalysis(lens="temporal_trend", sub_question="a"),
            DerivedAnalysis(lens="dimensional_breakdown", sub_question="b"),
        ]),
        contract=contract,
        scope=SCOPE,
    )
    assert [s.step_id for s in plan.derived] == ["s0_temporal_trend", "s1_dimensional_breakdown"]
    assert [s.requirement for s in plan.derived] == ["annual_movement", "product_contributors"]
    assert plan.derived[0].source == "gpr"
    assert plan.derived[0].scope == SCOPE


def test_an_unmet_requirement_carries_the_specific_reason_when_a_step_tried():
    contract = build_contract("performance_assessment")
    progress = PlanProgress(contract=contract)
    progress.record(StepOutcome("s0", "satisfied", "annual_movement", ("ev_1",)))
    progress.record(StepOutcome("s1", "no_data", "quarterly_comparison",
                                detail="2024 stops at Q2."))
    limitations = progress.limitations()
    assert "2024 stops at Q2." in limitations
    # The one nothing ever tried falls back to the requirement's own sentence.
    assert any("product split" in text or "reconcile" in text for text in limitations)


def test_a_turn_is_complete_only_when_every_requirement_is_satisfied():
    contract = build_contract("performance_assessment")
    progress = PlanProgress(contract=contract)
    assert not progress.is_complete()
    for key in contract.keys():
        progress.record(StepOutcome(f"s_{key}", "satisfied", key, ("ev",)))
    assert progress.is_complete()
    assert stop_reason(progress) == "requirements satisfied"


def test_a_repair_replaces_a_step_outcome_rather_than_adding_one():
    progress = PlanProgress(contract=build_contract("lookup"))
    progress.record(StepOutcome("s0", "failed", "direct_value"))
    progress.record(StepOutcome("s0", "satisfied", "direct_value", ("ev",)))
    assert progress.steps_run == 1
    assert progress.is_complete()


# --------------------------------------------------------------------------- #
# Phase 4 — the drill-down follows the results
# --------------------------------------------------------------------------- #


def _progress_with_drilldown():
    contract = build_contract(
        "performance_assessment", conditions=["material_product_movement"]
    )
    return PlanProgress(contract=contract)


def test_a_large_percentage_on_a_tiny_base_does_not_displace_a_real_driver():
    """The regression matrix names this one explicitly."""
    findings = [
        Finding("Product_Line", "Property", change=-300.0, contribution_pp=-17.6),
        Finding("Product_Line", "Novelty", change=-0.8, contribution_pp=-0.05),
    ]
    material = material_findings(findings, headline=-250.0)
    assert [f.value for f in material] == ["Property"]


def test_growth_is_as_worth_investigating_as_decline():
    findings = [Finding("Product_Line", "Cyber", change=90.0, contribution_pp=5.3)]
    assert material_findings(findings, headline=-250.0)


def test_the_drilldown_target_comes_from_the_observed_movement():
    progress = _progress_with_drilldown()
    findings = [
        Finding("Product_Line", "Casualty", change=-40.0),
        Finding("Product_Line", "Property", change=-300.0),
    ]
    steps = decide_next_steps(progress, findings, headline=-250.0)
    assert len(steps) == 1
    assert steps[0].value == "Property"
    assert steps[0].scope == {"Product_Line": "Property"}
    assert "-300.0" in steps[0].reason


def test_no_material_movement_means_no_drilldown_and_a_bounded_stop():
    progress = _progress_with_drilldown()
    findings = [Finding("Product_Line", "Property", change=-0.5)]
    steps = decide_next_steps(progress, findings, headline=-250.0)
    assert steps == ()
    assert stop_reason(progress) == "no further step was justified"


def test_a_contract_without_the_drilldown_never_admits_one():
    progress = PlanProgress(contract=build_contract("performance_assessment"))
    findings = [Finding("Product_Line", "Property", change=-300.0)]
    assert decide_next_steps(progress, findings, headline=-250.0) == ()


def test_an_already_satisfied_drilldown_is_not_repeated():
    progress = _progress_with_drilldown()
    progress.record(StepOutcome("f0", "satisfied", "industry_concentration", ("ev",)))
    findings = [Finding("Product_Line", "Property", change=-300.0)]
    assert decide_next_steps(progress, findings, headline=-250.0) == ()


def test_an_exhausted_budget_stops_the_loop_and_says_which_limit_it_hit():
    progress = PlanProgress(contract=_progress_with_drilldown().contract,
                            budget=Budget(max_steps=1))
    progress.record(StepOutcome("s0", "satisfied", "annual_movement", ("ev",)))
    findings = [Finding("Product_Line", "Property", change=-300.0)]
    steps = decide_next_steps(progress, findings, headline=-250.0)
    assert steps == ()
    assert "step limit of 1" in stop_reason(progress)


def test_one_round_adds_at_most_one_drilldown_by_default():
    progress = _progress_with_drilldown()
    findings = [
        Finding("Product_Line", "Property", change=-300.0),
        Finding("Product_Line", "Casualty", change=-200.0),
        Finding("Product_Line", "Marine", change=-180.0),
    ]
    assert len(decide_next_steps(progress, findings, headline=-250.0)) == 1


# --------------------------------------------------------------------------- #
# Phase 4 — reading findings out of real evidence
# --------------------------------------------------------------------------- #


def test_a_contribution_row_becomes_a_finding():
    finding = finding_from_row(
        {"Product_Line": "Property", "contribution": -300.0, "contribution_pp": -17.6}
    )
    assert finding.value == "Property" and finding.change == -300.0
    assert finding.contribution_pp == -17.6


def test_a_per_year_comparison_row_becomes_a_finding():
    finding = finding_from_row({"Product_Line": "Property", "2024": 1200.0, "2025": 900.0})
    assert finding.change == pytest.approx(-300.0)


def test_an_ambiguous_row_yields_no_finding_rather_than_a_guess():
    """Two dimensions means two possible drill-downs, and they are different queries."""
    assert finding_from_row(
        {"Product_Line": "Property", "SIC_Major_Class": "Manufacturing",
         "2024": 1.0, "2025": 2.0}
    ) is None


def test_a_row_that_is_not_a_comparison_yields_nothing():
    assert finding_from_row({"Product_Line": "Property", "2025": 900.0}) is None


def test_a_stated_headline_is_preferred_over_the_sum_of_the_parts():
    rows = [
        {"scope": "total", "change": -250.0},
        {"Product_Line": "Property", "change": -300.0},
    ]
    assert headline_from_rows(rows) == -250.0


def test_findings_are_read_only_from_validated_evidence():
    good = _evidence(rows=[{"Product_Line": "Property", "2024": 1200.0, "2025": 900.0}])
    bad = _evidence(
        parameters={"x": 1},
        rows=[{"Product_Line": "Ghost", "2024": 1.0, "2025": 999.0}],
        status=FAILED,
    )
    findings, _headline = observe([good, bad])
    assert [f.value for f in findings] == ["Property"]


def test_the_same_slice_seen_by_two_lenses_is_counted_once():
    first = _evidence(rows=[{"Product_Line": "Property", "2024": 1200.0, "2025": 900.0}])
    second = _evidence(
        parameters={"group_by": ["Product_Line"], "lens": "market"},
        rows=[{"Product_Line": "Property", "2024": 1200.0, "2025": 900.0}],
    )
    findings, _ = observe([first, second])
    assert len(findings) == 1
