"""Change columns, cross-metric commentary, and the chart plan.

The second round of the same complaint: a table of levels with no direction, one
chart that shows a timeline and nothing else, and commentary that still reads as
facts rather than analysis. Each test here pins one of the things that fixes.

Expected values come from `tests.evaluation.oracles`, which reads the scenario in
plain Python and imports none of the code under test.
"""
from __future__ import annotations

import logging

import pytest

from core.analytics import positioning as P
from core.answers import positioning_claims as PC
from core.answers.chart_plan import (
    CHANGE_AXIS,
    PREMIUM_AXIS,
    build_chart_plan,
    contribution_chart,
    quarterly_chart,
    quarterly_rows_from,
)
from tests.evaluation import scenario
from tests.evaluation.warehouse import build_engine

SCOPE = {
    "Country": scenario.COUNTRY,
    "Carrier_Group": scenario.CARRIER,
    "Year": scenario.CURRENT_YEAR,
}


@pytest.fixture(scope="module")
def engine():
    return build_engine()


@pytest.fixture(scope="module")
def compared(engine):
    return P.build_positioning_comparison(
        filters=SCOPE, subject=scenario.CARRIER, engine=engine
    )


def _position(pack, name):
    return next(p for p in pack.positions if p.slice == name)


def _row(pack, name):
    return next(r for r in pack.rows() if r[pack.dimension] == name)


def _quarterly_rows(prior_flat: bool = True):
    prior = [425.0] * 4 if prior_flat else [400.0, 410.0, 430.0, 440.0]
    current = [425.0, 420.0, 315.0, 290.0]
    return [{"Quarter": f"Q{i + 1}", "2024": prior[i], "2025": current[i]} for i in range(4)]


def _render(spec):
    """One chart spec through the real renderer, without the critic's log noise."""
    from ui.evidence import build_views

    logging.disable(logging.INFO)
    try:
        return build_views([spec.as_view()])[0]
    finally:
        logging.disable(logging.NOTSET)


# --------------------------------------------------------------------------- #
# Direction in the table
# --------------------------------------------------------------------------- #


def test_share_movements_are_reported_in_points(compared):
    """A share is not a rate: 70.6% to 62.1% is 8.5 points, not 12%."""
    position = _position(compared, "Property")
    assert position.portfolio_change == pytest.approx(-8.5, abs=0.2)
    assert position.wallet_change == pytest.approx(-9.2, abs=0.2)


def test_rank_change_is_positive_when_the_carrier_improves():
    """Rank 4 to rank 2 is a gain of two places, so the arrow points up."""
    assert P.SlicePosition("X", rank=2, prior_rank=4).rank_change == 2


def test_a_change_cell_carries_its_direction(compared):
    assert _row(compared, "Property")[P.WALLET_CHANGE].startswith(P.DOWN)
    assert _row(compared, "Cyber")[P.PORTFOLIO_CHANGE].startswith(P.UP)


def test_no_movement_and_no_comparison_render_differently(compared):
    """A dash means compared and unchanged; blank means never compared."""
    assert _row(compared, "Cyber")[P.RANK_CHANGE] == P.FLAT
    assert _row(compared, "Marine")[P.RANK_CHANGE] is None


def test_a_scope_with_no_prior_year_still_produces_a_table(engine):
    pack = P.build_positioning_comparison(
        filters={**SCOPE, "Year": scenario.PRIOR_YEAR - 5},
        subject=scenario.CARRIER, engine=engine,
    )
    assert all(p.prior_share_of_wallet is None for p in pack.positions)


def test_the_table_colours_direction_from_the_glyph_not_the_column_name():
    from ui.components.evidence import _direction_styles

    queries = [s["if"]["filter_query"] for s in _direction_styles(["SoW change"])]
    assert any(P.UP in q for q in queries)
    assert any(P.DOWN in q for q in queries)


def test_figures_right_align_and_labels_do_not():
    from ui.components.evidence import _figure_columns
    from ui.evidence import EvidenceView

    view = EvidenceView(
        label="t",
        columns=["Product line", "Carrier premium", "SoW change", "Rank"],
        records=[{"Product line": "Property", "Carrier premium": "900",
                  "SoW change": f"{P.DOWN} 9.2 pts", "Rank": "#1 of 2"}],
    )
    aligned = _figure_columns(view)
    assert "Carrier premium" in aligned and "SoW change" in aligned
    assert "Product line" not in aligned and "Rank" not in aligned


# --------------------------------------------------------------------------- #
# Cross-metric commentary
# --------------------------------------------------------------------------- #


def test_a_decline_that_outran_the_market_is_named_as_such(compared):
    claims = {c.kind: c.text for c in PC.compile_positioning(compared).claims}
    assert "ground" in claims
    assert "wallet share" in claims["ground"]


def test_losing_volume_while_gaining_share_reads_as_a_market_fall():
    """The reading a premium column cannot give, and the one a reader needs."""
    position = P.SlicePosition(
        "Property", carrier_premium=900.0, prior_premium=1200.0,
        marsh_premium=1770.0, share_of_wallet=50.8, prior_share_of_wallet=45.0,
    )
    claim, _facts = PC.ground_claim(position, "Product_Line")
    assert "lost volume, not lost position" in claim.text


def test_growing_while_losing_share_reads_as_lagging_the_market():
    position = P.SlicePosition(
        "Cyber", carrier_premium=190.0, prior_premium=100.0,
        marsh_premium=900.0, share_of_wallet=21.0, prior_share_of_wallet=30.0,
    )
    claim, _facts = PC.ground_claim(position, "Product_Line")
    assert "more slowly than the Marsh book" in claim.text


def test_a_share_move_within_noise_earns_no_ground_claim():
    position = P.SlicePosition(
        "Flat", carrier_premium=100.0, prior_premium=99.0,
        marsh_premium=500.0, share_of_wallet=20.1, prior_share_of_wallet=20.0,
    )
    assert PC.ground_claim(position, "Product_Line") is None


def test_the_book_changing_shape_is_reported(compared):
    claims = {c.kind: c.text for c in PC.compile_positioning(compared).claims}
    assert "changing shape" in claims["mix_shift"]


def test_a_rank_that_held_through_a_fall_is_reported(compared):
    claims = {c.kind: c.text for c in PC.compile_positioning(compared).claims}
    assert "held 1st place" in claims["standing"]


def test_the_commentary_covers_more_than_one_kind_of_reading(compared):
    """The original complaint: every sentence was the same kind of sentence."""
    kinds = {c.kind for c in PC.compile_positioning(compared).claims}
    assert {"position", "ground", "mix_shift", "standing"} <= kinds


def test_cross_metric_claims_rebuild_from_recorded_facts(compared):
    built = PC.compile_positioning(compared)
    rebuilt = PC.positioning_claims(built.facts)
    assert [c.text for c in rebuilt] == [c.text for c in built.claims]


def test_cross_metric_claims_assert_no_cause(compared):
    from core.answers.verification import check_causation

    for claim in PC.compile_positioning(compared).claims:
        assert check_causation(claim.text) == []


# --------------------------------------------------------------------------- #
# The chart plan
# --------------------------------------------------------------------------- #


def test_a_performance_answer_carries_three_purposeful_charts(compared):
    plan = build_chart_plan(compared, quarterly_rows=_quarterly_rows(), scope=SCOPE)
    assert [spec.key for spec in plan] == ["quarterly", "contribution", "wallet"]


def test_each_chart_has_a_short_tab_and_a_fuller_title(compared):
    for spec in build_chart_plan(compared, quarterly_rows=_quarterly_rows(), scope=SCOPE):
        assert spec.tab and len(spec.tab) < 20
        assert len(spec.title) > len(spec.tab)


def test_a_title_describes_the_chart_not_the_question():
    title = quarterly_chart(_quarterly_rows(), scope=SCOPE).title
    assert "2024" in title and "2025" in title and scenario.COUNTRY in title


def test_one_year_of_quarters_is_not_a_comparison():
    assert quarterly_chart([{"Quarter": "Q1", "2025": 425.0}]) is None


def test_a_quarter_missing_a_year_is_left_out_of_the_pair():
    """A half-drawn pair reads as a collapse rather than as missing data."""

    class _Fact:
        def __init__(self, period, support):
            self.dims = {"grain": "quarter", "period": period}
            self.support = [support]

    rows = quarterly_rows_from(
        [_Fact("Q1", {"2024": 1.0, "2025": 2.0}), _Fact("Q2", {"2025": 3.0})],
        current_year=2025, prior_year=2024,
    )
    assert [r["Quarter"] for r in rows] == ["Q1"]


def test_the_movement_chart_plots_change_so_the_offset_is_visible(compared):
    values = [row[CHANGE_AXIS] for row in contribution_chart(compared, scope=SCOPE).rows]
    assert min(values) < 0 < max(values)


def test_the_axes_name_the_measure_not_the_series():
    """A y-axis reading "2024, 2025" names the series and says nothing."""
    spec = quarterly_chart(_quarterly_rows(), scope=SCOPE)
    assert spec.y_title == PREMIUM_AXIS
    assert spec.x_title == "Quarter"


def test_the_rendered_chart_uses_the_declared_axis_titles():
    figure = _render(quarterly_chart(_quarterly_rows(), scope=SCOPE)).figure
    assert figure.layout.yaxis.title.text == "Premium"
    assert figure.layout.xaxis.title.text == "Quarter"


def test_a_flat_prior_year_keeps_its_series():
    """A constant MEASURE is still the comparison that was asked for."""
    view = _render(quarterly_chart(_quarterly_rows(prior_flat=True), scope=SCOPE))
    assert sorted(trace.name for trace in view.figure.data) == ["2024", "2025"]


def test_a_constant_dimension_is_still_treated_as_useless():
    """Narrowing the rule to numerics must not make it useless for labels."""
    import pandas as pd

    from core.charts.critic import classify_columns

    frame = pd.DataFrame([{"Country": "Singapore", "Premium": 1.0},
                          {"Country": "Singapore", "Premium": 2.0}])
    assert classify_columns(frame)["Country"].kind == "constant"


def test_a_thin_turn_produces_fewer_charts_never_a_blank_one():
    assert build_chart_plan(P.PositioningPack(), quarterly_rows=[]) == []
