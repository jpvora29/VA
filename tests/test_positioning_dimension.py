"""Cutting a positioning table by a dimension the question has not already fixed.

The reported failure: "Where is maximum penetration possible for Zurich in Canada
for property product?" ran for five minutes and returned almost nothing. The scope
fixed `Product_Line`, the table cut by `Product_Line`, and the result was a single
row whose share of the book was 100% by construction — a table with nothing to
compare, for a question that is entirely about comparison.

The fix is a ladder: cut by the finest level the scope has NOT fixed, so a
question about one product breaks out by industry within it.
"""
from __future__ import annotations

import pytest

from core.analysis import build_contract
from core.analysis.operation import PENETRATION, detect_operation
from core.analytics import dimensions as D
from core.analytics.positioning import build_positioning_comparison
from core.answers import positioning_claims as PC
from tests.evaluation import scenario
from tests.evaluation.warehouse import build_engine

LADDER = list(D.LADDER)
BASE = {"Country": scenario.COUNTRY, "Carrier_Group": scenario.CARRIER, "Year": 2025}


@pytest.fixture(scope="module")
def engine():
    return build_engine()


# --------------------------------------------------------------------------- #
# The ladder
# --------------------------------------------------------------------------- #


def test_an_unfixed_scope_cuts_by_product():
    assert D.choose_dimension(BASE, ladder=LADDER) == "Product_Line"


def test_a_pinned_product_cuts_by_industry_instead():
    """The reported case. Cutting by the pinned column gives a one-row table."""
    scope = {**BASE, "Product_Line": "Property"}
    assert D.choose_dimension(scope, ladder=LADDER) == "SIC_Major_Class"


def test_a_pinned_industry_drills_to_sub_industry():
    scope = {**BASE, "Product_Line": "Property", "SIC_Major_Class": "Manufacturing"}
    assert D.choose_dimension(scope, ladder=LADDER) == "SIC_Minor_Class"


def test_a_scope_fixed_all_the_way_down_has_nothing_left_to_break_out():
    """"" is a real answer: skip the table rather than draw a single row."""
    scope = {column: "x" for column in LADDER}
    assert D.choose_dimension(scope, ladder=LADDER) == ""


def test_a_multi_valued_filter_is_not_a_fixed_level():
    """"Property and Casualty" says nothing about which one — still worth cutting."""
    scope = {**BASE, "Product_Line": ["Property", "Casualty"]}
    assert D.choose_dimension(scope, ladder=LADDER) == "Product_Line"


def test_a_single_valued_list_is_fixed():
    scope = {**BASE, "Product_Line": ["Property"]}
    assert D.choose_dimension(scope, ladder=LADDER) == "SIC_Major_Class"


def test_the_caption_names_only_the_levels_above_the_cut():
    """Carrier, country and year are already on screen as scope chips."""
    scope = {**BASE, "Product_Line": "Property"}
    caption = D.describe_scope(scope, "SIC_Major_Class")
    assert caption == " within Property"
    assert scenario.COUNTRY not in caption


def test_a_drilldown_steps_one_level_down():
    assert D.drilldown_dimension("Product_Line", ladder=LADDER) == "SIC_Major_Class"
    assert D.drilldown_dimension("SIC_Major_Class", ladder=LADDER) == "SIC_Minor_Class"
    assert D.drilldown_dimension("Client_Segment", ladder=LADDER) == ""


def test_a_level_the_flow_lacks_is_stepped_past():
    thin = ["Product_Line", "Client_Segment"]
    assert D.drilldown_dimension("Product_Line", ladder=thin) == "Client_Segment"


def test_each_level_has_a_name_a_reader_would_use():
    assert D.label_for("SIC_Major_Class") == "industry"
    assert D.label_for("SIC_Minor_Class") == "sub-industry"
    assert D.label_for("Product_Line") == "product"


# --------------------------------------------------------------------------- #
# The table that results
# --------------------------------------------------------------------------- #


def test_a_single_product_question_produces_a_multi_row_table(engine):
    scope = {**BASE, "Product_Line": "Property"}
    pack = build_positioning_comparison(
        dimension=D.choose_dimension(scope, ladder=LADDER),
        filters=scope, subject=scenario.CARRIER, engine=engine,
    )
    assert len(pack.rows()) > 1
    assert pack.dimension == "SIC_Major_Class"


def test_that_table_still_carries_every_requested_column(engine):
    from core.analytics import positioning as P

    scope = {**BASE, "Product_Line": "Property"}
    pack = build_positioning_comparison(
        dimension="SIC_Major_Class", filters=scope,
        subject=scenario.CARRIER, engine=engine,
    )
    row = pack.rows()[0]
    for column in (P.CARRIER_PREMIUM, P.MARSH_PREMIUM, P.SHARE_OF_WALLET,
                   P.SHARE_OF_PORTFOLIO, P.RANK):
        assert column in row


def test_cutting_by_the_pinned_column_is_what_produced_one_row(engine):
    """Pins the behaviour that was wrong, so the fix cannot quietly regress."""
    scope = {**BASE, "Product_Line": "Property"}
    pack = build_positioning_comparison(
        dimension="Product_Line", filters=scope,
        subject=scenario.CARRIER, engine=engine,
    )
    assert len(pack.rows()) == 1


# --------------------------------------------------------------------------- #
# The question type
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("question", [
    "Where is maximum penetration possible for Zurich in Canada for property product?",
    "Where can Zurich grow in Canada?",
    "Show me headroom for Zurich in Canada",
    "Which industries are we under-indexed in?",
])
def test_a_penetration_question_is_recognised(question):
    assert detect_operation(question, depth="analytical") == PENETRATION


def test_a_penetration_question_asks_only_for_position():
    """It ran a full performance sweep before, which is why it took five minutes."""
    contract = build_contract(PENETRATION, allowed_sources=["gpr"])
    assert contract.keys() == ("positioning",)


def test_a_performance_question_now_carries_position_too():
    contract = build_contract("performance_assessment", allowed_sources=["gpr"])
    assert "positioning" in contract.keys()


def test_a_growth_question_is_not_mistaken_for_a_breakdown():
    """"Where can we grow by product" asks about growth, not about the cut."""
    assert detect_operation("Where can Zurich grow by product?") == PENETRATION


# --------------------------------------------------------------------------- #
# What a penetration answer leads with
# --------------------------------------------------------------------------- #


def test_a_penetration_answer_leads_with_the_unheld_book(engine):
    scope = {**BASE, "Product_Line": "Property"}
    pack = build_positioning_comparison(
        dimension="SIC_Major_Class", filters=scope,
        subject=scenario.CARRIER, engine=engine,
    )
    claims = PC.compile_positioning(pack, focus=PC.PENETRATION).claims
    assert claims[0].kind == "headroom"


def test_a_performance_answer_still_leads_with_scale(engine):
    pack = build_positioning_comparison(
        filters=BASE, subject=scenario.CARRIER, engine=engine
    )
    assert PC.compile_positioning(pack).claims[0].kind == "position"


def test_the_focus_is_chosen_from_the_question():
    assert PC.focus_for("Where can Zurich grow?") == PC.PENETRATION
    assert PC.focus_for("How did Zurich perform in 2025?") == ""


# --------------------------------------------------------------------------- #
# Separation of insight and evidence
# --------------------------------------------------------------------------- #


def test_each_column_is_labelled_so_the_reader_knows_where_to_start():
    from ui.components.chatbot import _reading_area

    points, visual = _reading_area("HEAD", "PROSE", "VIEWS")[0].children
    assert points.children[0].children == "Insight"
    assert visual.children[0].children == "Evidence"


def test_an_answer_with_no_chart_is_not_labelled_at_all():
    """A single column needs no signpost saying which column it is."""
    from ui.components.chatbot import _reading_area

    assert _reading_area("HEAD", "PROSE", None) == ["HEAD", "PROSE"]


def test_the_stylesheet_styles_the_column_labels():
    from pathlib import Path

    css = Path("assets/va_shell_chat.css").read_text(encoding="utf-8")
    assert ".answer-column-label" in css
