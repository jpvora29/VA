"""Phase 3: the two decompositions a performance answer is built from.

Every expected figure comes from `tests.evaluation.oracles`, which sums the
scenario in plain Python and never imports `core.analytics`. So these tests
compare two independent derivations rather than restating the primitive's own
formula back at it.

The failure modes under test are the ones the plan names: comparing Q1 against
the preceding Q4, adding per-slice percentages, clamping a contribution and
losing the offset, dividing by a zero base, and presenting a missing period as a
zero.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.analytics.movement import (
    LAPSED,
    NEW,
    PRESENT,
    compute_aligned_periods,
    compute_contribution,
    contribution_points,
    percent_change,
    presence,
    reconcile,
    resolve_year_pair,
)
from core.analytics.types import PrimitiveArgs
from tests.evaluation import oracles, scenario
from tests.evaluation.warehouse import build_engine

SCOPE = {"Carrier_Group": scenario.CARRIER, "Country": scenario.COUNTRY}


@pytest.fixture(scope="module")
def engine():
    return build_engine()


def _args(**overrides) -> PrimitiveArgs:
    base = dict(flow="gpr", metric="premium", group_by=(), filters=dict(SCOPE))
    base.update(overrides)
    return PrimitiveArgs(**base)


def _by_dim(facts, key):
    return {fact.dims[key]: fact for fact in facts}


# --------------------------------------------------------------------------- #
# Pure arithmetic
# --------------------------------------------------------------------------- #


def test_percent_change_is_none_on_a_zero_base_not_zero_and_not_infinite():
    assert percent_change(10.0, 0.0) is None
    assert percent_change(0.0, 0.0) is None
    assert percent_change(90.0, 100.0) == -10.0


def test_contribution_points_are_additive_where_percentages_are_not():
    prior_total = oracles.annual_premium(scenario.PRIOR_YEAR)
    points = [
        contribution_points(movement.absolute, prior_total)
        for movement in oracles.product_movements().values()
    ]
    assert sum(points) == pytest.approx(oracles.headline_movement().percent, abs=0.05)


def test_contribution_points_are_none_against_a_zero_prior_total():
    assert contribution_points(50.0, 0.0) is None


def test_presence_separates_a_new_slice_from_a_lapsed_one():
    assert presence(current=10.0, prior=0.0) == NEW
    assert presence(current=0.0, prior=10.0) == LAPSED
    assert presence(current=10.0, prior=8.0) == PRESENT


def test_reconcile_reports_a_residual_rather_than_claiming_completeness():
    complete = reconcile([-300.0, -40.0, 90.0], headline=-250.0)
    assert complete.is_complete and complete.residual == pytest.approx(0.0)
    assert complete.limitation("product") == ""

    partial = reconcile([-300.0, -40.0], headline=-250.0)
    assert not partial.is_complete
    assert partial.residual == pytest.approx(90.0)
    assert "not attributed" in partial.limitation("product")


def test_a_requested_year_that_is_absent_yields_no_comparison():
    rows = [{"yr": 2024}, {"yr": 2025}]
    assert resolve_year_pair(rows, 2025, 2024) == (2025, 2024)
    assert resolve_year_pair(rows, 2025, 2019) == (None, None)
    assert resolve_year_pair([{"yr": 2025}]) == (None, None)


# --------------------------------------------------------------------------- #
# Corresponding-period comparison
# --------------------------------------------------------------------------- #


def test_quarters_are_compared_against_the_same_quarter_a_year_earlier(engine):
    facts = compute_aligned_periods(_args(), engine=engine)
    changes = {fact.dims["position"]: fact.value for fact in facts}
    expected = {q: m.absolute for q, m in oracles.quarter_movements().items()}
    assert changes == pytest.approx(expected)


def test_the_aligned_comparison_names_both_years_it_used(engine):
    fact = compute_aligned_periods(_args(), engine=engine)[0]
    assert fact.dims["year"] == scenario.CURRENT_YEAR
    assert fact.dims["prior_year"] == scenario.PRIOR_YEAR
    assert fact.formula == "2025 Q1 - 2024 Q1"


def test_the_quarterly_gap_lands_where_the_scenario_puts_it(engine):
    facts = compute_aligned_periods(_args(), engine=engine)
    worst = min(facts, key=lambda fact: fact.value)
    quarter, movement = oracles.widest_quarter_gap()
    assert worst.dims["position"] == quarter
    assert worst.value == pytest.approx(movement.absolute)


def test_aligned_quarters_reconcile_to_the_headline(engine):
    facts = compute_aligned_periods(_args(), engine=engine)
    result = reconcile([fact.value for fact in facts], oracles.headline_movement().absolute)
    assert result.is_complete


def test_a_sequential_quarter_comparison_would_give_a_different_answer(engine):
    """Guards the distinction the new primitive exists for.

    Q1 2025 against Q4 2024 is a real number and the wrong one. If this ever
    stops differing, the primitive has quietly become `compute_period_change`.
    """
    from core.analytics.library import compute_period_change

    aligned = {f.dims["position"]: f.value for f in compute_aligned_periods(_args(), engine=engine)}
    sequential = compute_period_change(_args(), engine=engine, grain="quarter")
    q3 = next(f for f in sequential if f.dims["period"] == "2025-Q3")

    quarters_2025 = oracles.premium_by_quarter(scenario.CURRENT_YEAR)
    within_year = (quarters_2025[3] - quarters_2025[2]) / quarters_2025[2] * 100
    year_on_year = oracles.quarter_movements()[3]

    # The sequential primitive answers "how did Q3 compare with Q2?"...
    assert q3.value == pytest.approx(round(within_year, 1))
    # ...while the aligned one answers "how did Q3 compare with Q3 last year?".
    assert aligned[3] == pytest.approx(year_on_year.absolute)
    assert q3.value != pytest.approx(year_on_year.percent, abs=0.05)


def test_aligned_periods_hold_per_cut(engine):
    facts = compute_aligned_periods(_args(group_by=("Product_Line",)), engine=engine)
    cyber = [f for f in facts if f.dims.get("Product_Line") == "Cyber"]
    changes = {f.dims["position"]: f.value for f in cyber}
    prior = scenario.SUBJECT_BOOK["Cyber"][scenario.PRIOR_YEAR]
    current = scenario.SUBJECT_BOOK["Cyber"][scenario.CURRENT_YEAR]
    expected = {
        q: sum(current[q].values()) - sum(prior[q].values()) for q in scenario.QUARTERS
    }
    assert changes == pytest.approx(expected)


def test_a_turn_pinned_to_one_year_still_gets_a_comparison(engine):
    """Dropping the period pin is what makes the comparison possible at all."""
    pinned = compute_aligned_periods(_args(filters={**SCOPE, "Year": 2025}), engine=engine)
    assert {f.dims["position"] for f in pinned} == set(scenario.QUARTERS)


def test_a_missing_quarter_is_reported_as_not_comparable_rather_than_zero():
    """A quarter the warehouse has not loaded is not a quarter that wrote nothing."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE GPR (Country TEXT, Carrier_Group TEXT, Product_Line TEXT, '
            'Billing_Date TEXT, Year INTEGER, Premium REAL)'
        ))
        conn.execute(
            text('INSERT INTO GPR VALUES (:c, :g, :p, :d, :y, :m)'),
            [
                dict(c="Singapore", g="ZURICH GROUP", p="Property", d="2024-02-15", y=2024, m=100.0),
                dict(c="Singapore", g="ZURICH GROUP", p="Property", d="2024-05-15", y=2024, m=100.0),
                dict(c="Singapore", g="ZURICH GROUP", p="Property", d="2025-02-15", y=2025, m=80.0),
            ],
        )
    facts = _by_dim(compute_aligned_periods(_args(), engine=engine), "position")
    assert facts[1].dims["comparable"] is True
    assert facts[1].value == pytest.approx(-20.0)
    assert facts[2].dims["comparable"] is False
    assert facts[2].dims["coverage"] == LAPSED
    assert facts[2].rendered == "not comparable"


def test_a_year_only_flow_yields_no_aligned_periods_rather_than_raising(engine):
    assert compute_aligned_periods(
        PrimitiveArgs(flow="survey", metric="score", filters={"Carrier": scenario.CARRIER}),
        engine=engine,
    ) == []


# --------------------------------------------------------------------------- #
# Contribution
# --------------------------------------------------------------------------- #


def test_the_headline_fact_matches_the_reference_calculation(engine):
    facts = compute_contribution(_args(group_by=("Product_Line",)), engine=engine)
    headline = facts[0]
    movement = oracles.headline_movement()
    assert headline.name == "headline_change"
    assert headline.value == pytest.approx(movement.absolute)
    assert headline.dims["percent"] == pytest.approx(round(movement.percent, 1))


def test_product_contributions_match_the_reference_calculation(engine):
    facts = compute_contribution(_args(group_by=("Product_Line",)), engine=engine)
    points = {
        fact.dims["Product_Line"]: fact.dims["contribution_pp"]
        for fact in facts
        if fact.name == "contribution"
    }
    assert points == pytest.approx(oracles.product_contributions(), abs=0.05)


def test_contributions_reconcile_to_the_headline(engine):
    facts = compute_contribution(_args(group_by=("Product_Line",)), engine=engine)
    headline, slices = facts[0], [f for f in facts if f.name == "contribution"]
    assert reconcile([f.value for f in slices], headline.value).is_complete


def test_a_growing_product_is_not_clamped_away(engine):
    """The offset is the finding; a clamp at the headline would delete it."""
    facts = compute_contribution(_args(group_by=("Product_Line",)), engine=engine)
    points = {f.dims["Product_Line"]: f.dims["contribution_pp"]
              for f in facts if f.name == "contribution"}
    assert points["Cyber"] > 0
    assert points["Property"] < facts[0].dims["percent"]


def test_the_largest_mover_leads_whichever_way_it_moved(engine):
    facts = compute_contribution(_args(group_by=("Product_Line",)), engine=engine)
    slices = [f for f in facts if f.name == "contribution"]
    worst, _ = oracles.largest_negative_contributor()
    assert slices[0].dims["Product_Line"] == worst


def test_industry_contributions_within_a_product_match_the_reference(engine):
    facts = compute_contribution(
        _args(group_by=("SIC_Major_Class",), filters={**SCOPE, "Product_Line": "Property"}),
        engine=engine,
    )
    changes = {
        fact.dims["SIC_Major_Class"]: fact.value
        for fact in facts
        if fact.name == "contribution"
    }
    expected = {k: m.absolute for k, m in oracles.industry_movements("Property").items()}
    assert changes == pytest.approx(expected)


def test_the_scope_that_was_asked_for_is_the_scope_that_runs(engine):
    """The out-of-scope country must never reach a Singapore total."""
    facts = compute_contribution(_args(group_by=("Product_Line",)), engine=engine)
    prior = facts[0].support[0][str(scenario.PRIOR_YEAR)]
    assert prior == pytest.approx(oracles.annual_premium(scenario.PRIOR_YEAR))
    assert prior < scenario.OTHER_COUNTRY_PREMIUM


def test_a_slice_present_in_only_one_year_is_labelled_not_silently_zeroed(engine):
    """Marine has market premium and no subject premium in either year."""
    facts = compute_contribution(
        PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                      filters={"Country": scenario.COUNTRY}),
        engine=engine,
    )
    marine = next(f for f in facts if f.dims.get("Product_Line") == "Marine")
    assert marine.dims["presence"] == PRESENT
    assert marine.dims["percent"] is not None


def test_a_single_year_book_yields_no_contribution_rather_than_a_fake_movement():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE GPR (Country TEXT, Carrier_Group TEXT, Product_Line TEXT, '
            'Billing_Date TEXT, Year INTEGER, Premium REAL)'
        ))
        conn.execute(
            text('INSERT INTO GPR VALUES (:c, :g, :p, :d, :y, :m)'),
            [dict(c="Singapore", g="ZURICH GROUP", p="Property", d="2025-02-15", y=2025, m=100.0)],
        )
    assert compute_contribution(_args(group_by=("Product_Line",)), engine=engine) == []
