"""Proves the fixture warehouse and the reference oracles agree.

Two independently written derivations of the same scenario: `oracles.py` sums
Python dicts, this module runs hand-written SQL against the built database. If
they agree, the warehouse is a faithful rendering of the scenario AND the oracle
is a faithful reading of it — established without either one consulting
`core.analytics`, which is what makes the oracle usable as an authority when the
library is the thing under test.

The scenario's own arithmetic is asserted here too (offsets net out, the cuts
reconcile), so a careless edit to a premium figure fails loudly rather than
quietly changing what "correct" means.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.evaluation import oracles, scenario
from tests.evaluation.warehouse import build_engine

# Quarter from Billing_Date, the way the production GPR schema has to derive it.
QUARTER_SQL = "((CAST(strftime('%m', Billing_Date) AS INTEGER) + 2) / 3)"

SUBJECT_WHERE = "Carrier_Group = :carrier AND Country = :country AND Year = :year"
SUBJECT_PARAMS = {"carrier": scenario.CARRIER, "country": scenario.COUNTRY}


@pytest.fixture(scope="module")
def engine():
    return build_engine()


def _scalar(engine, sql: str, **params) -> float:
    with engine.connect() as conn:
        value = conn.execute(text(sql), params).scalar()
    return float(value or 0.0)


def _mapping(engine, sql: str, **params) -> dict:
    with engine.connect() as conn:
        return {row[0]: float(row[1]) for row in conn.execute(text(sql), params)}


# --------------------------------------------------------------------------- #
# Warehouse against oracle
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("year", [scenario.PRIOR_YEAR, scenario.CURRENT_YEAR])
def test_annual_premium_matches_reference_sql(engine, year):
    total = _scalar(
        engine,
        f"SELECT SUM(Premium) FROM GPR WHERE {SUBJECT_WHERE}",
        **SUBJECT_PARAMS,
        year=year,
    )
    assert total == pytest.approx(oracles.annual_premium(year))


@pytest.mark.parametrize("year", [scenario.PRIOR_YEAR, scenario.CURRENT_YEAR])
def test_product_split_matches_reference_sql(engine, year):
    rows = _mapping(
        engine,
        f"SELECT Product_Line, SUM(Premium) FROM GPR WHERE {SUBJECT_WHERE} GROUP BY Product_Line",
        **SUBJECT_PARAMS,
        year=year,
    )
    assert rows == pytest.approx(oracles.premium_by_product(year))


@pytest.mark.parametrize("year", [scenario.PRIOR_YEAR, scenario.CURRENT_YEAR])
def test_quarter_split_matches_reference_sql(engine, year):
    rows = _mapping(
        engine,
        f"SELECT {QUARTER_SQL} AS q, SUM(Premium) FROM GPR WHERE {SUBJECT_WHERE} GROUP BY q",
        **SUBJECT_PARAMS,
        year=year,
    )
    assert rows == pytest.approx(oracles.premium_by_quarter(year))


def test_industry_split_within_a_product_matches_reference_sql(engine):
    rows = _mapping(
        engine,
        f"SELECT SIC_Major_Class, SUM(Premium) FROM GPR "
        f"WHERE {SUBJECT_WHERE} AND Product_Line = :product GROUP BY SIC_Major_Class",
        **SUBJECT_PARAMS,
        year=scenario.CURRENT_YEAR,
        product="Property",
    )
    assert rows == pytest.approx(
        oracles.premium_by_industry(scenario.CURRENT_YEAR, product="Property")
    )


def test_marsh_book_drops_only_the_carrier_filter(engine):
    """The denominator keeps country and year; losing either is the classic bug."""
    rows = _mapping(
        engine,
        "SELECT Product_Line, SUM(Premium) FROM GPR "
        "WHERE Country = :country AND Year = :year GROUP BY Product_Line",
        country=scenario.COUNTRY,
        year=scenario.CURRENT_YEAR,
    )
    assert rows == pytest.approx(oracles.marsh_book_by_product(scenario.CURRENT_YEAR))
    # The out-of-scope country carries enough volume that a lost filter is obvious.
    assert sum(rows.values()) < scenario.OTHER_COUNTRY_PREMIUM


def test_survey_response_counts_are_real_rows(engine):
    rows = _mapping(
        engine,
        "SELECT Attribute, COUNT(DISTINCT ResponseId) FROM Carriers "
        "WHERE Carrier = :carrier AND SurveyCountry = :country "
        "AND SurveyPractice = :practice AND Survey_Year = :year GROUP BY Attribute",
        carrier=scenario.CARRIER,
        country=scenario.COUNTRY,
        practice="Property",
        year=scenario.CURRENT_YEAR,
    )
    assert rows == pytest.approx(oracles.survey_response_counts(scenario.CURRENT_YEAR))


def test_survey_scores_match_reference(engine):
    rows = _mapping(
        engine,
        "SELECT Attribute, AVG(Score) FROM Carriers "
        "WHERE Carrier = :carrier AND SurveyCountry = :country "
        "AND SurveyPractice = :practice AND Survey_Year = :year GROUP BY Attribute",
        carrier=scenario.CARRIER,
        country=scenario.COUNTRY,
        practice="Property",
        year=scenario.CURRENT_YEAR,
    )
    assert rows == pytest.approx(oracles.survey_attribute_scores(scenario.CURRENT_YEAR))


# --------------------------------------------------------------------------- #
# The scenario says what it is meant to say
# --------------------------------------------------------------------------- #


def test_headline_is_a_material_decline():
    movement = oracles.headline_movement()
    assert movement.prior == 1700.0
    assert movement.current == 1450.0
    assert movement.absolute == -250.0
    assert movement.percent == pytest.approx(-14.7, abs=0.05)


def test_a_growing_product_offsets_the_decline():
    """Without this the scenario cannot catch an answer that reports only decline."""
    worst, worst_movement = oracles.largest_negative_contributor()
    best, best_movement = oracles.largest_positive_contributor()
    assert worst == "Property" and worst_movement.absolute == -300.0
    assert best == "Cyber" and best_movement.absolute == 90.0


def test_product_decomposition_reconciles_to_the_headline():
    assert oracles.decomposition_residual(oracles.product_movements()) == pytest.approx(0.0)


def test_quarter_decomposition_reconciles_to_the_headline():
    assert oracles.decomposition_residual(oracles.quarter_movements()) == pytest.approx(0.0)


def test_product_and_quarter_cuts_are_not_additive():
    """Both cuts explain the SAME -250; adding them is the double-count to catch."""
    products = sum(m.absolute for m in oracles.product_movements().values())
    quarters = sum(m.absolute for m in oracles.quarter_movements().values())
    assert products == quarters == oracles.headline_movement().absolute
    assert products + quarters != oracles.headline_movement().absolute


def test_the_gap_is_concentrated_in_the_second_half():
    movements = oracles.quarter_movements()
    quarter, widest = oracles.widest_quarter_gap()
    assert quarter == 4 and widest.absolute == -135.0
    assert movements[1].absolute == 0.0


def test_contributions_may_exceed_the_headline_percentage():
    """Property alone is worse than the net; clamping it would hide the offset."""
    contributions = oracles.product_contributions()
    assert contributions["Property"] < oracles.headline_movement().percent
    assert contributions["Cyber"] > 0
    assert sum(contributions.values()) == pytest.approx(
        oracles.headline_movement().percent
    )


def test_manufacturing_is_the_weak_industry_inside_property():
    movements = oracles.industry_movements("Property")
    assert movements["Manufacturing"].absolute == -220.0
    assert oracles.decomposition_residual(movements) == pytest.approx(
        oracles.headline_movement().absolute - (-300.0)
    )


def test_marine_is_whitespace_and_property_is_not():
    whitespace = oracles.whitespace_products(scenario.CURRENT_YEAR)
    assert set(whitespace) == {"Marine"}
    assert whitespace["Marine"] > 0


def test_thin_survey_practice_is_below_the_reporting_threshold():
    reportable = oracles.reportable_practices(scenario.CURRENT_YEAR)
    assert "Property" in reportable
    assert "Cyber" not in reportable


def test_survey_attributes_move_in_both_directions():
    movements = oracles.survey_attribute_movements()
    assert movements["Responsiveness"] == -1.0
    assert movements["Underwriting expertise"] == 0.1


def test_premium_and_survey_coverage_do_not_match():
    """Marine is written but never surveyed — a limitation, not a zero."""
    assert "Marine" in oracles.premium_only_products()
    assert oracles.survey_only_practices() == ()


def test_percentage_change_on_a_zero_base_raises_rather_than_returning_a_number():
    with pytest.raises(ZeroDivisionError):
        oracles.Movement(prior=0.0, current=10.0).percent
