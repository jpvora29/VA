"""Positioning: the numbers that turn a premium figure into an insight.

The complaint this answers was that an answer "talks about premium in one line,
stating numbers rather than reading as insight". The fix is not wording — it is
four more numbers per slice (share of the carrier's own book, share of Marsh's
wallet, rank, unheld market) and a claim library that pairs them into an
argument.

Expected values come from `tests.evaluation.oracles`, which reads the scenario in
plain Python and imports none of the code under test.
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.analytics import positioning as P
from core.answers import positioning_claims as PC
from tests.evaluation import oracles, scenario
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
def pack(engine):
    return P.build_positioning(filters=SCOPE, subject=scenario.CARRIER, engine=engine)


def _position(pack, name):
    return next(p for p in pack.positions if p.slice == name)


# --------------------------------------------------------------------------- #
# The numbers
# --------------------------------------------------------------------------- #


def test_carrier_premium_matches_the_reference_calculation(pack):
    expected = oracles.premium_by_product(scenario.CURRENT_YEAR)
    actual = {p.slice: p.carrier_premium for p in pack.positions if p.carrier_premium}
    assert actual == pytest.approx(expected)


def test_marsh_premium_keeps_country_and_year_and_drops_only_the_carrier(pack):
    expected = oracles.marsh_book_by_product(scenario.CURRENT_YEAR)
    actual = {p.slice: p.marsh_premium for p in pack.positions if p.marsh_premium}
    assert actual == pytest.approx(expected)


def test_share_of_wallet_is_the_carrier_over_the_marsh_book(pack):
    for position in pack.positions:
        if position.share_of_wallet is None:
            continue
        expected = oracles.carrier_share_of_market(scenario.CURRENT_YEAR, position.slice)
        assert position.share_of_wallet == pytest.approx(expected, abs=0.05)


def test_share_of_portfolio_sums_to_the_whole_book(pack):
    shares = [p.share_of_portfolio for p in pack.positions if p.share_of_portfolio]
    assert sum(shares) == pytest.approx(100.0, abs=0.2)


def test_rank_is_against_other_carriers_not_against_itself(pack):
    """Computed inside the carrier's own filter every slice reads "#1 of 1"."""
    assert _position(pack, "Property").rank_of == 2
    assert _position(pack, "Casualty").rank == 2


def test_movement_matches_the_reference_calculation(pack):
    expected = {k: v.absolute for k, v in oracles.product_movements().items()}
    actual = {p.slice: p.movement for p in pack.positions if p.movement is not None}
    assert actual == pytest.approx(expected)


def test_a_slice_the_carrier_does_not_write_reports_absence_not_zero(pack):
    """Marine has Marsh premium and no carrier premium. Zero would be a claim."""
    marine = _position(pack, "Marine")
    assert marine.marsh_premium == pytest.approx(
        oracles.marsh_book_by_product(scenario.CURRENT_YEAR)["Marine"]
    )
    assert marine.carrier_premium is None
    assert marine.share_of_wallet is None
    assert not marine.has_position


def test_headroom_is_the_book_placed_with_others(pack):
    property_ = _position(pack, "Property")
    assert property_.headroom == pytest.approx(
        (property_.marsh_premium or 0) - (property_.carrier_premium or 0)
    )


def test_headroom_is_unknown_rather_than_whole_when_participation_is_unknown(pack):
    assert _position(pack, "Marine").headroom is None


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #


def test_the_table_carries_every_column_the_reader_asked_for(pack):
    row = pack.rows()[0]
    # Category, the market, the carrier, its movement, penetration, mix,
    # standing — in that order. The movement has a column of its own so that
    # every figure in the table stays a sortable number.
    assert list(row) == [
        pack.heading, P.MARSH_PREMIUM, P.CARRIER_PREMIUM, P.MOVEMENT_PERCENT,
        P.SHARE_OF_WALLET, P.SHARE_OF_PORTFOLIO, P.RANK, P.RANK_FIELD,
    ]


def test_the_table_leads_with_the_largest_line(pack):
    assert pack.rows()[0][pack.heading] == "Property"


def test_an_absent_figure_renders_blank_rather_than_zero(pack):
    marine = next(r for r in pack.rows() if r[pack.heading] == "Marine")
    assert marine[P.CARRIER_PREMIUM] is None
    assert marine[P.SHARE_OF_WALLET] is None
    assert marine[P.MARSH_PREMIUM] is not None  # the market IS known


def test_numeric_rows_omit_absent_columns_so_no_fact_is_worth_zero(pack):
    # The machine-facing rows keep the RAW column name; only the display rows
    # carry the human heading. Two consumers, two renderings, one source.
    marine = next(r for r in pack.numeric_rows() if r[pack.dimension] == "Marine")
    assert P.CARRIER_PREMIUM not in marine
    assert marine[P.MARSH_PREMIUM] > 0


def test_the_two_renderings_agree_on_the_same_positions(pack):
    """Same slices in the same order; only the column KEY differs by audience."""
    display = [r[pack.heading] for r in pack.rows()]
    numeric = [r[pack.dimension] for r in pack.numeric_rows()]
    assert display == numeric


def test_the_slice_column_is_headed_in_english_not_schema(pack):
    assert pack.heading == "Product line"
    assert pack.dimension == "Product_Line"


# --------------------------------------------------------------------------- #
# The insight sentences
# --------------------------------------------------------------------------- #


def test_a_position_claim_pairs_scale_with_penetration(pack):
    claims = PC.compile_positioning(pack).claims
    lead = claims[0]
    assert lead.kind == "position"
    assert "of the carrier's book" in lead.text
    assert "of Marsh's" in lead.text


def test_the_answer_leads_with_the_line_that_matters_to_the_carrier(pack):
    """A dominant share of a tiny line must not outrank most of the book."""
    assert PC.compile_positioning(pack).claims[0].text.startswith("Property")


def test_rank_is_stated_only_when_there_are_other_carriers_to_rank_against(pack):
    claims = {c.text.split()[0]: c.text for c in PC.compile_positioning(pack).claims}
    assert "ranking 1st of 2 carriers" in claims["Property"]
    # Cyber is the only carrier in its line; "#1" there would read as a win.
    assert "ranking" not in claims["Cyber"]


def test_concentration_is_reported_as_a_risk(pack):
    claims = PC.compile_positioning(pack).claims
    concentration = next(c for c in claims if c.kind == "concentration")
    assert "concentrated" in concentration.text
    assert "62.1%" in concentration.text


def test_headroom_is_phrased_as_observation_not_opportunity(pack):
    claims = PC.compile_positioning(pack).claims
    headroom = next(c for c in claims if c.kind == "headroom")
    assert "placed with other carriers" in headroom.text
    for banned in ("opportunity", "winnable", "addressable", "potential"):
        assert banned not in headroom.text.lower()


def test_positioning_claims_assert_no_cause():
    """These sentences must pass the Phase 7 causation check like any other."""
    from core.answers.verification import check_causation
    from tests.evaluation.warehouse import build_engine as _engine

    pack = P.build_positioning(filters=SCOPE, subject=scenario.CARRIER, engine=_engine())
    for claim in PC.compile_positioning(pack).claims:
        assert check_causation(claim.text) == []


def test_an_unremarkable_slice_earns_no_sentence_of_its_own():
    """Otherwise the answer becomes the list of numbers it is replacing."""
    middling = P.SlicePosition("Middling", carrier_premium=10.0, marsh_premium=100.0,
                               share_of_wallet=15.0, share_of_portfolio=20.0)
    assert not PC._notable(middling)


def test_a_thin_position_is_worth_saying_even_on_a_small_line():
    thin = P.SlicePosition("Thin", carrier_premium=1.0, marsh_premium=100.0,
                           share_of_wallet=1.0, share_of_portfolio=5.0)
    assert PC._notable(thin)


def test_per_slice_sentences_are_bounded(pack):
    claims = PC.compile_positioning(pack, limit=1).claims
    assert sum(1 for c in claims if c.kind == "position") == 1


def test_an_empty_pack_produces_nothing_rather_than_raising():
    assert PC.compile_positioning(P.PositioningPack()).claims == ()


# --------------------------------------------------------------------------- #
# Reconstruction, so a saved answer still verifies
# --------------------------------------------------------------------------- #


def test_claims_rebuild_from_the_facts_an_answer_recorded(pack):
    built = PC.compile_positioning(pack)
    rebuilt = PC.positioning_claims(built.facts)
    assert [c.text for c in rebuilt] == [c.text for c in built.claims]


def test_a_turn_with_no_positioning_evidence_produces_no_positioning_claims():
    from core.answers.facts import AnswerFact

    ordinary = AnswerFact(id="f1", metric="premium", value=1.0, unit="currency",
                          rendered="$1", dimensions=(("product_line", "Property"),),
                          source_id="sql", lens="temporal_trend")
    assert PC.positioning_claims([ordinary]) == ()


# --------------------------------------------------------------------------- #
# Chart look and feel
# --------------------------------------------------------------------------- #


def _bar(rows, y):
    from ui.chart_functions import generate_chart

    figure, _note = generate_chart(
        df=pd.DataFrame(rows),
        chart_outputs={"chart_type": "bar", "x": list(rows[0])[0], "y": [y], "title": "t"},
    )
    return figure


def test_a_chart_with_negative_bars_draws_the_zero_line():
    """Without it a decline and a small gain look alike pointing different ways."""
    rows = [{"Quarter": f"Q{q}", "Change": m.absolute}
            for q, m in oracles.quarter_movements().items()]
    assert _bar(rows, "Change").layout.yaxis.zeroline is True


def test_an_all_positive_chart_does_not_draw_a_second_baseline():
    rows = [{"Product": "Property", "Premium": 900.0}, {"Product": "Cyber", "Premium": 190.0}]
    assert _bar(rows, "Premium").layout.yaxis.zeroline is False


def test_a_mixed_series_is_coloured_by_direction():
    from ui.color_pallet import ColorPalette

    rows = [{"Product": k, "Change": v.absolute} for k, v in oracles.product_movements().items()]
    colours = _bar(rows, "Change").data[0].marker.color
    assert ColorPalette.positive in colours and ColorPalette.negative in colours


def test_an_all_negative_series_is_not_painted_red_throughout():
    """Colouring every bar red adds no information and reads as alarm."""
    rows = [{"Quarter": f"Q{q}", "Change": m.absolute}
            for q, m in oracles.quarter_movements().items()]
    colours = _bar(rows, "Change").data[0].marker.color
    assert isinstance(colours, str)


def test_a_trace_value_is_tested_for_emptiness_without_numpy_ambiguity():
    """`bar.y or []` raises on an ndarray; the guard must be an explicit check."""
    rows = [{"Product": k, "Change": v.absolute} for k, v in oracles.product_movements().items()]
    assert _bar(rows, "Change") is not None


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


def test_an_answer_with_a_chart_reads_side_by_side():
    from ui.components.chatbot import _reading_area

    area = _reading_area("HEAD", "PROSE", "VIEWS")
    assert len(area) == 1
    split = area[0]
    assert split.className == "answer-split"
    assert [child.className for child in split.children] == ["answer-points", "answer-visual"]


def test_an_answer_with_no_chart_keeps_the_full_column():
    """Half a card of text beside empty space reads as a page that failed to load."""
    from ui.components.chatbot import _reading_area

    assert _reading_area("HEAD", "PROSE", None) == ["HEAD", "PROSE"]


def test_the_points_come_before_the_visual_so_stacking_keeps_reading_order():
    from ui.components.chatbot import _reading_area

    split = _reading_area("HEAD", "PROSE", "VIEWS")[0]
    points, visual = split.children
    # Each column opens with its label; the content follows in reading order, so
    # a stacked layout still puts the argument before the evidence.
    assert points.children[1:] == ["HEAD", "PROSE"]
    assert visual.children[1:] == ["VIEWS"]


def test_the_stylesheet_collapses_the_split_on_a_narrow_screen():
    from pathlib import Path

    css = Path("assets/va_shell_chat.css").read_text(encoding="utf-8")
    assert ".answer-split" in css
    assert "grid-template-columns: 1fr;" in css
    # Both tracks must refuse to be pushed wider by a wide table.
    assert css.count("min-width: 0;") >= 2
