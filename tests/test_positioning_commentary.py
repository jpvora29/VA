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
    return next(r for r in pack.rows() if r[pack.heading] == name)


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
    """The movement sits with the figure it describes, not in a column of its own."""
    assert P.DOWN in _row(compared, "Property")[P.CARRIER_PREMIUM]
    assert P.UP in _row(compared, "Cyber")[P.CARRIER_PREMIUM]


def test_no_movement_and_no_comparison_render_differently(compared):
    """A dash means compared and unchanged; blank means never compared."""
    assert _row(compared, "Cyber")[P.RANK].endswith(P.FLAT)
    assert _row(compared, "Marine")[P.RANK] is None


def test_a_scope_with_no_prior_year_still_produces_a_table(engine):
    pack = P.build_positioning_comparison(
        filters={**SCOPE, "Year": scenario.PRIOR_YEAR - 5},
        subject=scenario.CARRIER, engine=engine,
    )
    assert all(p.prior_share_of_wallet is None for p in pack.positions)


def test_the_table_colours_direction_from_the_glyph_not_the_column_name():
    from ui.components.evidence import _direction_styles

    queries = [s["if"]["filter_query"] for s in _direction_styles([P.CARRIER_PREMIUM])]
    assert any(P.UP in q for q in queries)
    assert any(P.DOWN in q for q in queries)


def test_figures_right_align_and_labels_do_not():
    from ui.components.evidence import _figure_columns
    from ui.evidence import EvidenceView

    view = EvidenceView(
        label="t",
        columns=["Product line", "Marsh premium", "Share of wallet", "Rank"],
        records=[{"Product line": "Property", "Marsh premium": "$1.77M",
                  "Share of wallet": "50.8%", "Rank": "#1 of 2"}],
    )
    aligned = _figure_columns(view)
    assert "Marsh premium" in aligned and "Share of wallet" in aligned
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

# --------------------------------------------------------------------------- #
# Money scale, column order and table styling
# --------------------------------------------------------------------------- #


def _millions_engine():
    """The fixture at a realistic scale, so the table renders millions."""
    from sqlalchemy import create_engine, text

    import tests.evaluation.warehouse as W
    from tests.evaluation import scenario as S

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        for name, columns in (("GPR", W.GPR_COLUMNS), ("Peers", W.PEERS_COLUMNS)):
            conn.execute(text(f'CREATE TABLE "{name}" ({", ".join(columns)})'))
        rows = [W.gpr_row(cell) for cell in S.all_cells()]
        for row in rows:
            row["Premium"] = row["Premium"] * 1000.0
        W._insert(conn, "GPR", rows)
        W._insert(conn, "Peers", W.peers_rows())
    return engine


def test_money_uses_one_scale_across_the_whole_table():
    """Per-row units ("$1.2M" above "$840k") make a column impossible to compare."""
    assert P.money_scale([1_770_000.0, 900_000.0]) == (1e6, "M")
    assert P.money_scale([1_770.0, 900.0]) == (1e3, "k")
    assert P.money_scale([12.0, 4.0]) == (1.0, "")


def test_an_absent_figure_does_not_drag_the_scale_down():
    assert P.money_scale([2_000_000.0, None]) == (1e6, "M")


def test_premium_reads_in_millions_at_a_realistic_scale():
    from tests.evaluation import scenario as S

    pack = P.build_positioning_comparison(
        filters={"Country": S.COUNTRY, "Carrier_Group": S.CARRIER, "Year": 2025},
        subject=S.CARRIER, engine=_millions_engine(),
    )
    assert pack.money_suffix() == "M"
    row = pack.rows()[0]
    assert row[P.MARSH_PREMIUM] == "$1.77M"
    assert row[P.CARRIER_PREMIUM].startswith("$0.90M")


def test_the_columns_are_in_the_order_a_reader_reads_them(compared):
    assert list(compared.rows()[0]) == [
        compared.heading, P.MARSH_PREMIUM, P.CARRIER_PREMIUM,
        P.SHARE_OF_WALLET, P.SHARE_OF_PORTFOLIO, P.RANK,
    ]


def test_the_market_comes_before_the_carrier():
    """The carrier's figure means nothing until the reader has seen the market's."""
    assert P.COLUMNS.index(P.MARSH_PREMIUM) < P.COLUMNS.index(P.CARRIER_PREMIUM)


def test_the_premium_cell_carries_its_own_movement(compared):
    cell = _row(compared, "Property")[P.CARRIER_PREMIUM]
    assert P.DOWN in cell and "%" in cell


def test_the_rank_cell_carries_its_own_movement(compared):
    assert _row(compared, "Cyber")[P.RANK].endswith(P.FLAT)


def test_a_slice_with_no_prior_period_shows_a_bare_figure():
    """No comparison is not the same as no movement."""
    position = P.SlicePosition("X", carrier_premium=5_000_000.0)
    cell = P._premium_cell(position, 1e6, "M")
    assert cell == "$5.00M"


def test_the_header_is_brand_navy_on_white():
    from ui.components.evidence import _TABLE_STYLE

    header = _TABLE_STYLE["style_header"]
    assert header["backgroundColor"] == "#000F47"
    assert header["color"] == "#FFFFFF"


def test_the_rows_are_black_arial_on_white():
    from ui.components.evidence import _TABLE_STYLE

    cell = _TABLE_STYLE["style_cell"]
    assert cell["color"] == "#000000"
    assert cell["fontSize"] == "12px"
    assert cell["fontFamily"].startswith("Arial")
    assert cell["backgroundColor"] == "#FFFFFF"
    assert _TABLE_STYLE["style_data"]["backgroundColor"] == "#FFFFFF"


def test_the_filter_row_does_not_inherit_the_navy_header():
    from ui.components.evidence import _TABLE_STYLE

    assert _TABLE_STYLE["style_filter"]["color"] == "#000000"


@pytest.mark.parametrize("cell, aligned", [
    ("$1.77M", True),
    ("$0.90M  ▼ 25.0%", True),
    ("50.8%", True),
    ("#1 of 2", False),
    ("Property", False),
])
def test_alignment_is_decided_from_the_cell_not_the_column_name(cell, aligned):
    from ui.components.evidence import _FIGURE

    assert bool(_FIGURE.match(cell)) is aligned

# --------------------------------------------------------------------------- #
# A null in the axis column must not kill the chart
# --------------------------------------------------------------------------- #
#
# `groupby(dropna=False)` puts NaN in the index, which becomes a null category,
# and pandas rejects those outright: "Categorical categories cannot be null".
# One unlabelled row was taking down the whole chart.


def _sorted_bar(rows):
    import logging

    import pandas as pd

    from ui.chart_functions import generate_chart

    logging.disable(logging.INFO)
    try:
        return generate_chart(
            df=pd.DataFrame(rows),
            chart_outputs={"chart_type": "bar", "x": "Product_Line",
                           "y": ["Premium"], "title": "t", "sort": "desc"},
        )
    finally:
        logging.disable(logging.NOTSET)


NULL_ROWS = [
    {"Product_Line": "Property", "Premium": 100.0},
    {"Product_Line": None, "Premium": 50.0},
    {"Product_Line": "Cyber", "Premium": 30.0},
]


def test_a_null_axis_value_does_not_break_the_chart():
    figure, note = _sorted_bar(NULL_ROWS)
    assert figure is not None
    assert note == "Successful"


def test_the_unlabelled_slice_is_named_rather_than_dropped():
    """Dropping the row would quietly change the total the chart shows."""
    from ui.chart_functions import UNLABELLED

    figure, _note = _sorted_bar(NULL_ROWS)
    assert UNLABELLED in list(figure.data[0].x)
    assert sum(figure.data[0].y) == pytest.approx(180.0)


def test_a_blank_string_is_treated_the_same_as_a_null():
    figure, _note = _sorted_bar([
        {"Product_Line": "Property", "Premium": 100.0},
        {"Product_Line": "   ", "Premium": 20.0},
    ])
    from ui.chart_functions import UNLABELLED

    assert UNLABELLED in list(figure.data[0].x)


def test_a_numeric_axis_is_left_alone():
    """"Not specified" is not a year, and a missing number has no position."""
    import pandas as pd

    from ui.chart_functions import label_unlabelled

    frame = pd.DataFrame([{"Year": 2024, "Premium": 1.0}, {"Year": None, "Premium": 2.0}])
    assert label_unlabelled(frame, "Year")["Year"].isna().any()


def test_a_clean_axis_is_unchanged():
    import pandas as pd

    from ui.chart_functions import label_unlabelled

    frame = pd.DataFrame([{"Product_Line": "Property", "Premium": 1.0}])
    assert label_unlabelled(frame, "Product_Line") is frame
