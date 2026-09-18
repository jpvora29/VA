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
from core.analytics import positioning as P
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

# --------------------------------------------------------------------------- #
# A table on most questions, including ones that name no carrier
# --------------------------------------------------------------------------- #


def test_a_question_with_no_carrier_still_gets_a_table(engine):
    from tests.evaluation import scenario as S

    pack = P.build_positioning_comparison(
        filters={"Country": S.COUNTRY, "Year": 2025}, subject="", engine=engine
    )
    assert pack.is_market_view
    assert len(pack.rows()) > 1


def test_a_market_table_drops_the_columns_a_carrier_would_own(engine):
    """Share of wallet and rank are undefined without a carrier to measure."""
    from tests.evaluation import scenario as S

    pack = P.build_positioning_comparison(
        filters={"Country": S.COUNTRY, "Year": 2025}, subject="", engine=engine
    )
    columns = list(pack.rows()[0])
    assert P.SHARE_OF_WALLET not in columns
    assert P.RANK not in columns
    assert P.CARRIER_PREMIUM not in columns
    assert P.MARSH_PREMIUM in columns


def test_a_market_share_column_sums_to_the_whole_book(engine):
    """The carrier primitive returns a share PER CARRIER; that column hit 175%."""
    from tests.evaluation import scenario as S

    pack = P.build_positioning_comparison(
        filters={"Country": S.COUNTRY, "Year": 2025}, subject="", engine=engine
    )
    shares = [r[P.SHARE_OF_MARKET] for r in pack.rows()]
    assert sum(shares) == pytest.approx(100.0, abs=0.2)


def test_the_market_share_column_is_named_differently_from_the_carrier_one():
    """Two different denominators must not share a heading readers would compare."""
    assert P.SHARE_OF_MARKET != P.SHARE_OF_PORTFOLIO


def test_a_carrier_question_still_gets_the_full_table(engine):
    from tests.evaluation import scenario as S

    pack = P.build_positioning_comparison(
        filters={"Country": S.COUNTRY, "Carrier_Group": S.CARRIER, "Year": 2025},
        subject=S.CARRIER, engine=engine,
    )
    assert not pack.is_market_view
    assert P.SHARE_OF_WALLET in pack.rows()[0]


def test_the_node_no_longer_refuses_a_question_with_no_carrier():
    """The gate that returned nothing for a market question is gone."""
    import inspect

    from core.graph import analyst_subgraph as sub

    source = inspect.getsource(sub.positioning_node)
    assert "if not subject:" not in source


def test_every_premium_question_shape_reaches_the_table():
    from core.analysis import build_contract
    from core.analysis.operation import detect_operation
    from core.graph.analyst_subgraph import _POSITIONING_REQUIREMENTS as REQUIRED

    questions = [
        "How was Zurich performance in Singapore in 2025?",
        "What was Zurich premium in Canada in 2025?",
        "Why did Zurich premium fall?",
        "Break down Zurich premium by product",
        "Where can Zurich grow in Canada?",
        "Tell me about Zurich in Canada",
    ]
    for question in questions:
        operation = detect_operation(question, depth="analytical")
        keys = set(build_contract(operation, allowed_sources=["gpr"]).keys())
        assert keys & REQUIRED, question


def test_a_survey_question_does_not_get_a_premium_table():
    """A premium table answers nothing a perception question asked."""
    from core.analysis import build_contract
    from core.analysis.operation import detect_operation
    from core.graph.analyst_subgraph import _POSITIONING_REQUIREMENTS as REQUIRED

    operation = detect_operation("How do brokers rate Zurich?", depth="analytical")
    keys = set(build_contract(operation, allowed_sources=["survey"]).keys())
    assert not (keys & REQUIRED)

# --------------------------------------------------------------------------- #
# The table has to REACH the reader, not merely be computed
# --------------------------------------------------------------------------- #
#
# It was built, it fed the commentary, and it was never rendered: the evidence
# panel is assembled from `analyst_charts` alone, so a result set absent from
# that list does not appear however carefully it was assembled. These tests walk
# the real path from pack to rendered view.


def _panel_views(state):
    from ui.callbacks import _evidence_specs
    from ui.evidence import build_views

    import logging
    logging.disable(logging.INFO)
    try:
        return build_views(_evidence_specs(state, "premium"))
    finally:
        logging.disable(logging.NOTSET)


def _carrier_pack(engine):
    from tests.evaluation import scenario as S

    return P.build_positioning_comparison(
        filters={"Country": S.COUNTRY, "Carrier_Group": S.CARRIER, "Year": 2025},
        subject=S.CARRIER, engine=engine,
    )


def test_the_positioning_table_reaches_a_rendered_view(engine):
    from core.graph.analyst_subgraph import _positioning_view
    from tests.evaluation import scenario as S

    scope = {"Country": S.COUNTRY, "Carrier_Group": S.CARRIER, "Year": 2025}
    view = _panel_views({"analyst_charts": [_positioning_view(_carrier_pack(engine), scope)]})[0]
    assert view.label == "Position"
    assert P.SHARE_OF_WALLET in view.columns
    assert view.records


def test_that_view_is_a_table_not_an_empty_chart(engine):
    """A view with no chart spec renders its rows; one with a broken spec shows nothing."""
    from core.graph.analyst_subgraph import _positioning_view
    from tests.evaluation import scenario as S

    scope = {"Country": S.COUNTRY, "Carrier_Group": S.CARRIER, "Year": 2025}
    view = _panel_views({"analyst_charts": [_positioning_view(_carrier_pack(engine), scope)]})[0]
    assert not view.has_chart
    assert view.note


def test_the_table_sits_alongside_the_charts(engine):
    """Three charts and the table, each its own tab."""
    from core.answers.chart_plan import build_chart_plan
    from core.graph.analyst_subgraph import _positioning_view
    from tests.evaluation import scenario as S

    scope = {"Country": S.COUNTRY, "Carrier_Group": S.CARRIER, "Year": 2025}
    pack = _carrier_pack(engine)
    quarterly = [{"Quarter": f"Q{i}", "2024": 400.0 + i, "2025": 380.0 + i} for i in range(1, 5)]
    specs = [s.as_view() for s in build_chart_plan(pack, quarterly_rows=quarterly, scope=scope)]
    specs.append(_positioning_view(pack, scope))

    views = _panel_views({"analyst_charts": specs})
    assert [v.label for v in views][-1] == "Position"
    assert sum(1 for v in views if v.has_chart) >= 1


def test_the_short_tab_name_survives_the_ui_layer(engine):
    """The panel was dropping `tab`, so every tab fell back to a long title."""
    from core.answers.chart_plan import quarterly_chart

    quarterly = [{"Quarter": f"Q{i}", "2024": 400.0 + i, "2025": 380.0 + i} for i in range(1, 5)]
    spec = quarterly_chart(quarterly, scope={"Country": "Canada"}).as_view()
    assert _panel_views({"analyst_charts": [spec]})[0].label == "Quarterly"


def test_a_view_with_no_chart_spec_still_renders_its_rows():
    view = _panel_views({"analyst_charts": [
        {"tab": "Raw", "rows": [{"A": 1}, {"A": 2}], "chart_data": {}, "lens": "x"}
    ]})[0]
    assert view.label == "Raw"
    assert len(view.records) == 2

# --------------------------------------------------------------------------- #
# A missing table must say why it is missing
# --------------------------------------------------------------------------- #
#
# Three early returns produced no table and no log line, so "the table did not
# appear" was undiagnosable from the outside. Each now reports its reason.


def _events(monkeypatch):
    seen = []
    import core.graph.analyst_subgraph as sub

    monkeypatch.setattr(sub, "log_event",
                        lambda logger, event, *a, **k: seen.append((event, k)))
    return seen


def _state(**overrides):
    from core.schemas.routing import QueryEntities, RoutingContext

    rc = RoutingContext(
        table_family="premium", intent_type="new_question",
        resolved_filters={"Carrier_Group": ["ZURICH GROUP"], "Country": ["Singapore"]},
        entities=QueryEntities(carriers=["Zurich"]),
    )
    state = {"question": "q", "route": "premium", "flow": "gpr",
             "routing_context": rc, "evidence": []}
    state.update(overrides)
    return state


def test_a_survey_turn_says_why_it_has_no_premium_table(monkeypatch):
    import core.graph.analyst_subgraph as sub

    seen = _events(monkeypatch)
    assert sub.positioning_node(_state(flow="survey")) == {}
    assert any(event == "positioning_skipped" for event, _ in seen)


def test_a_fully_pinned_question_says_there_is_nothing_left_to_break_out(monkeypatch):
    import core.graph.analyst_subgraph as sub
    from core.analysis import build_contract
    from core.schemas.routing import RoutingContext

    seen = _events(monkeypatch)
    pinned = {column: ["x"] for column in D.LADDER}
    rc = RoutingContext(table_family="premium", intent_type="new_question",
                        resolved_filters=pinned)
    state = _state(routing_context=rc,
                   contract=build_contract("performance_assessment", allowed_sources=["gpr"]))
    assert sub.positioning_node(state) == {}
    reasons = [k.get("reason", "") for event, k in seen if event == "positioning_skipped"]
    assert any("nothing to break out" in reason for reason in reasons)


def test_an_empty_result_says_the_scope_returned_nothing(monkeypatch):
    import core.graph.analyst_subgraph as sub
    from core.analysis import build_contract
    from core.analytics.positioning import PositioningPack

    seen = _events(monkeypatch)
    monkeypatch.setattr(sub, "build_positioning_comparison",
                        lambda **k: PositioningPack())
    state = _state(contract=build_contract("performance_assessment", allowed_sources=["gpr"]))
    assert sub.positioning_node(state) == {}
    assert any(event == "positioning_empty" for event, _ in seen)


def test_a_partly_computable_warehouse_still_gets_a_table(monkeypatch):
    """Losing the rank column must not cost the reader the whole table."""
    import core.graph.analyst_subgraph as sub
    from core.analysis import build_contract
    from core.analytics.positioning import PositioningPack, SlicePosition

    seen = _events(monkeypatch)
    partial = PositioningPack(
        (SlicePosition("Property", carrier_premium=9.0, marsh_premium=10.0),),
        "Product_Line", ("Rank",), "ZURICH GROUP",
    )
    monkeypatch.setattr(sub, "build_positioning_comparison", lambda **k: partial)
    out = sub.positioning_node(
        _state(contract=build_contract("performance_assessment", allowed_sources=["gpr"]))
    )
    assert out.get("chart_plan")
    assert any(event == "positioning_partial" for event, _ in seen)
