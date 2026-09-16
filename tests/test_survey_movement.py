"""Phase 5 (survey half): what a perception movement may and may not claim.

Every test here is a rule the premium side does not need, and each corresponds to
a way a survey figure turns into a false statement while every number in it stays
real: a score reported as a percentage, a composite attributed to attributes whose
weights nobody published, an average over four people, a comparison across a
changed questionnaire, a quarterly figure invented from an annual one, and a
co-movement written up as a cause.

Expected values come from `tests.evaluation.oracles`, which reads the scenario in
plain Python and knows nothing about this module.
"""
from __future__ import annotations

import pytest

from core.analysis import survey_movement as S
from tests.evaluation import oracles, scenario


def _scores():
    return {
        year: oracles.survey_attribute_scores(year)
        for year in (scenario.PRIOR_YEAR, scenario.CURRENT_YEAR)
    }


def _responses():
    return {
        year: oracles.survey_response_counts(year)
        for year in (scenario.PRIOR_YEAR, scenario.CURRENT_YEAR)
    }


def _comparison(**overrides):
    kwargs = dict(scores_by_year=_scores(), responses_by_year=_responses())
    kwargs.update(overrides)
    return S.build_comparison(**kwargs)


# --------------------------------------------------------------------------- #
# Comparable years
# --------------------------------------------------------------------------- #


def test_the_latest_two_survey_years_are_compared():
    assert S.comparable_survey_years([2023, 2024, 2025]) == (2025, 2024)


def test_a_single_survey_year_yields_no_comparison():
    """A snapshot presented as a movement is the failure this prevents."""
    assert S.comparable_survey_years([2025]) == (None, None)


def test_requested_years_the_data_does_not_have_yield_no_comparison():
    assert S.comparable_survey_years([2024, 2025], requested=[2019, 2020]) == (None, None)


def test_one_survey_year_produces_a_limitation_not_a_movement():
    comparison = S.build_comparison(scores_by_year={2025: {"Responsiveness": 6.0}})
    assert not comparison.is_comparable
    assert comparison.movements == ()
    assert any("one survey year" in text for text in comparison.limitations)


# --------------------------------------------------------------------------- #
# Points, never percent
# --------------------------------------------------------------------------- #


def test_attribute_movements_match_the_reference_calculation():
    movements = {m.attribute: m.delta for m in _comparison().movements}
    assert movements == pytest.approx(oracles.survey_attribute_movements())


def test_a_score_movement_is_rendered_in_points():
    """7.0 to 6.0 is down 1.0 point. "Down 14%" is a number with no meaning."""
    movement = S.AttributeMovement("Responsiveness", prior=7.0, current=6.0,
                                   prior_responses=8, current_responses=8)
    assert movement.delta == -1.0
    assert movement.rendered == "-1.00 points"
    assert not hasattr(movement, "percent")


def test_movements_are_found_in_both_directions():
    movements = {m.attribute: m.delta for m in _comparison().movements}
    assert movements["Responsiveness"] < 0
    assert movements["Underwriting expertise"] > 0


def test_the_largest_movement_is_by_magnitude_not_by_direction():
    assert _comparison().largest().attribute == "Responsiveness"


# --------------------------------------------------------------------------- #
# The response threshold
# --------------------------------------------------------------------------- #


def test_an_attribute_answered_by_too_few_people_is_withheld():
    comparison = S.build_comparison(
        scores_by_year={2024: {"Claims": 6.5}, 2025: {"Claims": 6.4}},
        responses_by_year={2024: {"Claims": 2}, 2025: {"Claims": 2}},
    )
    assert comparison.reportable == ()
    assert comparison.withheld[0].attribute == "Claims"
    assert any("responses" in text for text in comparison.limitations)


def test_a_thin_base_in_either_year_withholds_the_movement():
    """A movement is a statement about two numbers; both bases have to hold."""
    thin_prior = S.AttributeMovement("A", 7.0, 6.0, prior_responses=2, current_responses=90)
    thin_current = S.AttributeMovement("A", 7.0, 6.0, prior_responses=90, current_responses=2)
    assert not thin_prior.reportable
    assert not thin_current.reportable


def test_the_threshold_matches_the_rule_the_deck_applies():
    """One confidentiality commitment, applied the same way in both surfaces."""
    from studio.template_fill.survey.facts import MIN_RESPONSES as DECK_MIN

    assert S.MIN_RESPONSES == DECK_MIN


def test_the_scenarios_thin_practice_is_not_reportable():
    assert "Cyber" not in oracles.reportable_practices(scenario.CURRENT_YEAR)


# --------------------------------------------------------------------------- #
# Composite attribution
# --------------------------------------------------------------------------- #


def test_without_published_weights_attributes_are_observations_not_contributions():
    limitation = S.composite_attribution_limitation(None)
    assert "not published" in limitation
    assert limitation in _comparison().limitations


def test_with_published_weights_no_attribution_limitation_is_raised():
    assert S.composite_attribution_limitation({"Responsiveness": 0.5}) == ""


# --------------------------------------------------------------------------- #
# Questionnaire and population changes
# --------------------------------------------------------------------------- #


def test_an_attribute_present_in_only_one_year_is_a_questionnaire_change():
    """Not a score that moved to zero — a question that was not asked."""
    limitation = S.questionnaire_limitation(["A", "B"], ["A", "C"])
    assert "C" in limitation and "B" in limitation
    assert "questionnaire changed" in limitation


def test_an_unchanged_questionnaire_raises_nothing():
    assert S.questionnaire_limitation(["A", "B"], ["B", "A"]) == ""


def test_only_attributes_common_to_both_years_are_compared():
    comparison = S.build_comparison(
        scores_by_year={2024: {"A": 7.0, "B": 6.0}, 2025: {"A": 6.0, "C": 5.0}},
        responses_by_year={2024: {"A": 9, "B": 9}, 2025: {"A": 9, "C": 9}},
    )
    assert [m.attribute for m in comparison.movements] == ["A"]
    assert any("questionnaire changed" in text for text in comparison.limitations)


def test_a_halved_respondent_base_qualifies_the_comparison():
    assert "different population" in S.population_limitation(100, 40)


def test_a_stable_respondent_base_raises_nothing():
    assert S.population_limitation(100, 90) == ""


def test_a_missing_respondent_count_is_not_treated_as_a_population_collapse():
    assert S.population_limitation(0, 90) == ""


# --------------------------------------------------------------------------- #
# Reading the two datasets together
# --------------------------------------------------------------------------- #


def test_co_movement_is_described_without_asserting_a_cause():
    reading = S.read_together(premium_change=-250.0, survey_change=-1.0)
    assert reading.relation == S.AGREE
    assert "not evidence that either explains the other" in reading.text


def test_the_cross_reading_passes_the_causation_check():
    """The wording is built so an unsupported cause has nowhere to enter."""
    from core.answers.verification import check_causation

    for premium, survey in ((-250.0, -1.0), (250.0, -1.0), (-250.0, None)):
        reading = S.read_together(premium_change=premium, survey_change=survey)
        assert check_causation(reading.text) == []


def test_opposing_movements_are_reported_as_tension_not_contradiction():
    reading = S.read_together(premium_change=250.0, survey_change=-1.0)
    assert reading.relation == S.DIVERGE
    assert "opposite directions" in reading.text


def test_a_missing_survey_movement_is_stated_rather_than_implied():
    reading = S.read_together(premium_change=-250.0, survey_change=None)
    assert reading.relation == S.FLAT
    assert "No comparable perception movement" in reading.text


def test_comparing_at_a_finer_grain_than_the_survey_has_is_qualified():
    reading = S.read_together(premium_change=-250.0, survey_change=-1.0, grain="quarter")
    assert any("only available annually" in text for text in reading.limitations)


def test_no_quarterly_survey_figure_is_offered_beside_a_quarterly_premium_series():
    """The registry says the survey reaches a year and no further."""
    assert "no quarterly perception figure exists" in S.survey_grain_limitation()
