"""Phase 1: what a question is entitled to be answered with.

Covers the evidence contract (`core.analysis.requirements`), the operation and
source-restriction detectors (`core.analysis.operation`), and the premium/survey
alignment rules (`core.analysis.alignment`).

The recurring assertion is a distinction, not a value: an omitted requirement and
an unsatisfiable one must not be the same outcome, and a filter that cannot cross
between datasets must be dropped with a reason rather than carried on a guess.
"""
from __future__ import annotations

import pytest

from core.analysis import alignment, operation, requirements
from core.analysis.requirements import GPR, SURVEY, Policy, build_contract, get_requirements


# --------------------------------------------------------------------------- #
# The shipped configuration
# --------------------------------------------------------------------------- #


def test_intents_yaml_loads_and_declares_the_performance_contract():
    library = get_requirements()
    spec = library.intent("performance_assessment")
    assert spec is not None
    assert set(spec.required) == {
        "annual_movement",
        "product_contributors",
        "quarterly_comparison",
    }


def test_every_requirement_carries_a_publishable_limitation():
    """A requirement with no limitation sentence can only ever fail silently."""
    for requirement in get_requirements().requirements.values():
        assert requirement.limitation, f"{requirement.key} has no limitation text"
        assert requirement.evidence, f"{requirement.key} says nothing about its evidence"


def test_every_conditional_gate_names_a_known_condition():
    library = get_requirements()
    for spec in library.intents.values():
        for name, condition in spec.conditional.items():
            assert condition in requirements.KNOWN_CONDITIONS, (
                f"{spec.key}.{name} gates on unknown condition {condition!r}"
            )


def test_an_intent_can_be_found_by_alias():
    assert get_requirements().intent("how did they do").key == "performance_assessment"


# --------------------------------------------------------------------------- #
# Contract selection
# --------------------------------------------------------------------------- #


def test_performance_requires_movement_contributors_and_timing():
    contract = build_contract("performance_assessment")
    assert contract.keys() == (
        "annual_movement",
        "product_contributors",
        "quarterly_comparison",
    )


def test_a_drilldown_is_admitted_only_by_an_observed_result():
    """The industry cut follows the product findings, not the question's wording."""
    without = build_contract("performance_assessment")
    assert not without.requires("industry_concentration")

    with_finding = build_contract(
        "performance_assessment", conditions=["material_product_movement"]
    )
    assert with_finding.requires("industry_concentration")


def test_a_deferred_requirement_is_recorded_rather_than_forgotten():
    """The difference between 'not asked' and 'could not' lives in `deferred`."""
    contract = build_contract("performance_assessment")
    deferred = {r.key for r in contract.deferred}
    assert "industry_concentration" in deferred
    assert "survey_movement" in deferred


def test_survey_joins_only_when_comparable_data_exists():
    contract = build_contract(
        "performance_assessment", conditions=["comparable_survey_data"]
    )
    assert contract.requires("survey_movement")
    assert SURVEY in contract.sources()


def test_an_explicit_premium_only_restriction_drops_the_survey_requirement():
    contract = build_contract(
        "performance_assessment",
        conditions=["comparable_survey_data"],
        allowed_sources=[GPR],
    )
    assert not contract.requires("survey_movement")
    assert contract.sources() == (GPR,)
    assert "survey_movement" in {r.key for r in contract.deferred}


def test_whitespace_stays_out_of_performance_until_it_is_enabled():
    """Its thresholds are uncalibrated; the plan says not to enable it silently."""
    assert get_requirements().policy.whitespace_in_performance is False
    contract = build_contract("performance_assessment", conditions=["whitespace_enabled"])
    assert contract.requires("whitespace")  # only because the caller asserted it
    assert Policy().conditions() == frozenset()


def test_a_lookup_owes_one_value_and_nothing_else():
    contract = build_contract("lookup")
    assert contract.keys() == ("direct_value",)
    assert not contract.deferred


def test_an_unknown_intent_yields_an_empty_contract_rather_than_raising():
    contract = build_contract("interpretive_dance")
    assert contract.keys() == ()
    assert contract.sources() == ()


# --------------------------------------------------------------------------- #
# Source policy
# --------------------------------------------------------------------------- #


def test_the_configured_default_applies_when_nothing_is_requested():
    assert requirements.performance_sources() == (GPR, SURVEY)


def test_an_explicit_request_overrides_the_default_outright():
    assert requirements.performance_sources(requested=[GPR]) == (GPR,)
    assert requirements.performance_sources(requested=[SURVEY]) == (SURVEY,)


def test_an_unrecognised_request_falls_back_rather_than_emptying_the_answer():
    assert requirements.performance_sources(requested=["telepathy"]) == (GPR, SURVEY)


# --------------------------------------------------------------------------- #
# Operation detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "question, expected",
    [
        ("How was Zurich's performance in Singapore in 2025?", operation.PERFORMANCE),
        ("How did Zurich do in Singapore last year?", operation.PERFORMANCE),
        ("Why did Zurich's premium fall in Singapore?", operation.MOVEMENT),
        ("What drove the decline?", operation.MOVEMENT),
        ("Break down Zurich's premium by product", operation.BREAKDOWN),
        ("Show Zurich's premium across industries", operation.BREAKDOWN),
        ("What is Zurich's NPS in Singapore?", operation.PERCEPTION),
        ("How do brokers rate Zurich?", operation.PERCEPTION),
    ],
)
def test_operations_are_named_from_the_question(question, expected):
    assert operation.detect_operation(question) == expected


def test_a_movement_question_is_not_demoted_to_a_performance_review():
    """Both mention premium; only one asks for causes, and they owe different evidence."""
    assert operation.detect_operation("Why did premium decline?") == operation.MOVEMENT


def test_an_unnamed_analytical_question_still_gets_an_analytical_contract():
    assert operation.detect_operation("Tell me about Zurich", depth="analytical") == (
        operation.PERFORMANCE
    )
    assert operation.detect_operation("Tell me about Zurich") == operation.LOOKUP


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Zurich performance, premium only", (GPR,)),
        ("How did Zurich do? Just the premium please", (GPR,)),
        ("Zurich performance without the survey", (GPR,)),
        ("Survey only for Zurich", (SURVEY,)),
        ("How did Zurich do in Singapore?", ()),
    ],
)
def test_explicit_source_restrictions_are_detected(question, expected):
    assert operation.detect_source_restriction(question) == expected


def test_premium_only_wins_when_a_question_names_both_restrictions():
    assert operation.detect_source_restriction("premium only, no survey") == (GPR,)


# --------------------------------------------------------------------------- #
# Premium <-> survey alignment
# --------------------------------------------------------------------------- #


def test_the_column_mapping_comes_from_the_registry_not_a_literal():
    mappings = {m.role: (m.source_column, m.target_column)
                for m in alignment.column_mappings(GPR, SURVEY)}
    assert mappings["country"] == ("Country", "SurveyCountry")
    assert mappings["carrier"] == ("Carrier_Group", "Carrier")
    assert mappings["product"] == ("Product_Line", "SurveyPractice")


def test_the_shared_grain_with_the_survey_is_the_year():
    """The survey has Survey_Year and nothing finer, so no quarterly claim is possible."""
    assert alignment.shared_grain(GPR, SURVEY) == alignment.YEAR
    assert alignment.QUARTER in alignment.available_grains(GPR)
    assert alignment.QUARTER not in alignment.available_grains(SURVEY)


def test_a_filter_crosses_only_after_its_value_is_confirmed_on_the_far_side():
    present = lambda column, value: not (column == "SurveyPractice" and value == "Marine")
    aligned = alignment.align_scope(
        {"Carrier_Group": "ZURICH GROUP", "Country": "Singapore", "Product_Line": "Marine"},
        source_flow=GPR,
        target_flow=SURVEY,
        values_present=present,
    )
    assert aligned.carried == {"Carrier": "ZURICH GROUP", "SurveyCountry": "Singapore"}
    assert "product" in aligned.dropped
    assert "SurveyPractice" in aligned.dropped["product"]
    assert aligned.is_comparable


def test_an_unmappable_filter_is_dropped_with_a_reason_rather_than_carried():
    aligned = alignment.align_scope(
        {"SIC_Major_Class": "Manufacturing"}, source_flow=GPR, target_flow=SURVEY
    )
    assert aligned.carried == {}
    assert aligned.limitations()


def test_without_a_probe_no_value_is_assumed_present():
    """Silence must not be read as confirmation; that is how a bad join happens."""
    aligned = alignment.align_scope(
        {"Carrier_Group": "ZURICH GROUP"},
        source_flow=GPR,
        target_flow=SURVEY,
        values_present=lambda column, value: (_ for _ in ()).throw(RuntimeError("no db")),
    )
    assert aligned.carried == {}
    assert not aligned.is_comparable


def test_a_comparison_without_the_carrier_is_not_comparable():
    aligned = alignment.align_scope(
        {"Country": "Singapore"}, source_flow=GPR, target_flow=SURVEY,
        values_present=lambda column, value: True,
    )
    assert aligned.carried == {"SurveyCountry": "Singapore"}
    assert not aligned.is_comparable


def test_comparable_periods_are_the_intersection_not_the_union():
    assert alignment.comparable_periods([2023, 2024, 2025], [2024, 2025, 2026]) == (2024, 2025)
    assert alignment.comparable_periods([2025], [2024]) == ()
