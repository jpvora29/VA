"""The whole path a performance question takes, from wording to rendered table.

The reported failure: "How is the performance of AXA in Singapore for the year
2025?" came back as one line chart of year-on-year change, with no product table
and no second chart — the same answer it would have given before any of the
positioning work landed.

Every piece was in place. `detect_operation` reads the question as a performance
assessment, the contract owes the reader a `positioning` requirement,
`build_positioning` computes the six columns, and `positioning_node` returns them
as the answer's first view. None of it ran, because the ROUTER never sent the turn
to the analyst subgraph: `analysis_depth` was decided by a fast-tier model, and a
turn labelled "lookup" goes down the single-query rail, which has one chart, no
positioning node, and no way to produce a table.

So these tests walk the join, not the parts:

    question -> depth -> route -> contract -> positioning -> table + charts

The warehouse is `tests.evaluation`, whose schema mirrors `flows.yaml`, so the
primitives resolve real columns rather than convenient invented ones.

Run:  pytest tests/test_performance_question_reaches_the_table.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.agents import intent_classifier as ic
from core.agents.router import RouterNode
from core.analysis import build_contract
from core.analysis.operation import detect_operation
from core.analytics import positioning as P
from core.answers import chart_plan
from core.schemas.routing import RoutingContext
from tests.evaluation import scenario
from tests.evaluation.warehouse import build_engine

QUESTION = "How is the performance of AXA in singapore for the year 2025"
WHITESPACE = "Show it for each product and do whitespace analysis"
LOOKUP = "What is Zurich's premium in Canada in 2024?"

#: The three wordings the 18 September review reproduced as bypassing the table.
#: Each names the artifact the reader wants; each used to be read as a breakdown
#: or a lookup and answered by the single-query rail, which has no position node.
GROUPED = "How is the performance of AXA in singapore for the year 2025 by product"
COLUMNS_NAMED = (
    "Show Marsh premium, carrier premium, share of wallet, "
    "share of portfolio and rank by product"
)
TABLE_NAMED = "Show the positioning table for Zurich in Canada in 2025"


@pytest.fixture(scope="module")
def engine():
    return build_engine()


@pytest.fixture
def warehouse(engine, monkeypatch):
    """Point the primitives' default engine at the fixture warehouse.

    `positioning_node` takes no engine — it is a graph node, and its scope is the
    turn's filters — so the injection has to happen where the primitives look it
    up. Patching it here keeps the node under test exactly as production runs it.
    """
    from core.initialization import Initialization

    monkeypatch.setattr(Initialization, "engine", engine)
    return engine


def _routing_context(**overrides) -> RoutingContext:
    rc = RoutingContext(table_family="premium", intent_type="new_question")
    rc.resolved_filters = {
        "Carrier_Group": [scenario.CARRIER],
        "Country": [scenario.COUNTRY],
        "Year": [scenario.CURRENT_YEAR],
    }
    for key, value in overrides.items():
        setattr(rc, key, value)
    return rc


# --------------------------------------------------------------------------- #
# 1. Depth — decided from the question, not guessed by a model
# --------------------------------------------------------------------------- #


def test_a_performance_question_is_analytical_without_asking_a_model():
    """The bug in one line: this used to be a coin flip, and a "lookup" lost the table."""
    assert ic.analytical_floor(QUESTION) == "analytical"


def test_a_whitespace_question_is_analytical_too():
    assert ic.analytical_floor(WHITESPACE) == "analytical"


def test_the_floor_costs_no_model_call():
    from langchain_core.messages import HumanMessage

    def _boom(**kwargs):
        raise AssertionError("a performance question must not need the depth model")

    state = {"messages": [HumanMessage(content=QUESTION)],
             "routing_context": _routing_context(analysis_depth="lookup")}
    out = ic.IntentClassifier(depth_classifier=_boom).classify_intent(state)
    assert out["routing_context"].analysis_depth == "analytical"


def test_a_plain_lookup_still_goes_to_the_model():
    """The floor is narrow on purpose: a single-value question keeps the cheap path."""
    assert ic.analytical_floor(LOOKUP) == ""


def test_a_plain_breakdown_is_not_floored():
    """A GROUP BY is one query. Flooring it would send every listing to the analyst."""
    assert ic.analytical_floor("premium by product for Zurich") == ""


@pytest.mark.parametrize("question", [GROUPED, COLUMNS_NAMED, TABLE_NAMED])
def test_every_wording_that_asks_for_the_table_reaches_the_analyst(question):
    """The reproduced bypass: a grouping axis, or the columns named outright.

    "…by product" made the first one a breakdown, which is not floored; the other
    two named no operation the patterns knew, so they fell through to a lookup.
    All three end at `gpr_agent`, which has no positioning node.
    """
    assert ic.analytical_floor(question) == "analytical"


def test_a_grouping_axis_does_not_replace_the_operation():
    """"Performance … by product" is a performance question with a cut, not a cut."""
    from core.analysis.operation import PERFORMANCE

    assert detect_operation(GROUPED) == PERFORMANCE


def test_naming_the_columns_asks_for_the_position_table():
    from core.analysis.operation import POSITION

    assert detect_operation(COLUMNS_NAMED) == POSITION
    assert detect_operation(TABLE_NAMED) == POSITION


# --------------------------------------------------------------------------- #
# 2. Route — analytical depth is what reaches the analyst subgraph
# --------------------------------------------------------------------------- #


def test_the_classifier_marks_the_turn_analytical():
    from langchain_core.messages import HumanMessage

    state = {"messages": [HumanMessage(content=QUESTION)],
             "routing_context": _routing_context(analysis_depth="lookup")}
    classifier = ic.IntentClassifier(
        depth_classifier=lambda **kwargs: "lookup"  # the model that got it wrong
    )
    out = classifier.classify_intent(state)
    assert out["routing_context"].analysis_depth == "analytical"


def test_an_analytical_premium_turn_routes_to_the_analyst_agent():
    state = {"current_route": "premium",
             "routing_context": _routing_context(analysis_depth="analytical")}
    assert RouterNode.relevance_router(state) == "analyst_agent"


def test_a_lookup_turn_still_takes_the_single_query_rail():
    state = {"current_route": "premium",
             "routing_context": _routing_context(analysis_depth="lookup")}
    assert RouterNode.relevance_router(state) == "gpr_agent"


# --------------------------------------------------------------------------- #
# 3. Contract — the analyst owes the reader a position table
# --------------------------------------------------------------------------- #


def test_the_contract_requires_positioning():
    contract = build_contract(detect_operation(QUESTION), allowed_sources=("gpr",))
    assert "positioning" in contract.keys()


def test_the_contract_admits_the_positioning_node():
    from core.graph.analyst_subgraph import _POSITIONING_REQUIREMENTS

    contract = build_contract(detect_operation(QUESTION), allowed_sources=("gpr",))
    assert set(contract.keys()) & _POSITIONING_REQUIREMENTS


# --------------------------------------------------------------------------- #
# 4. The answer — a table the reader asked for, and more than one chart
# --------------------------------------------------------------------------- #


def test_the_turn_leads_with_a_position_table(warehouse):
    """End to end through the node: question wording in, rendered views out."""
    import core.graph.analyst_subgraph as sub

    state = {
        "question": QUESTION,
        "route": "premium",
        "flow": "gpr",
        "routing_context": _routing_context(analysis_depth="analytical"),
        "contract": build_contract(detect_operation(QUESTION), allowed_sources=("gpr",)),
        "evidence": [],
    }
    out = sub.positioning_node(state)
    views = out.get("chart_plan") or []

    assert views, "a performance turn must produce views"
    table = views[0]
    assert table["tab"] == "Position"
    assert table["rows"], "the table must carry rows, not only a title"
    assert not table["chart_data"], "the leading view is a table, not a chart"


def test_the_table_carries_the_columns_the_question_needs(warehouse):
    import core.graph.analyst_subgraph as sub

    state = {
        "question": QUESTION, "route": "premium", "flow": "gpr",
        "routing_context": _routing_context(analysis_depth="analytical"),
        "contract": build_contract(detect_operation(QUESTION), allowed_sources=("gpr",)),
        "evidence": [],
    }
    columns = list((sub.positioning_node(state)["chart_plan"][0]["rows"])[0].keys())

    # The slice column is named for the dimension the table cut by ("Product
    # line"), so it is checked by position rather than by a fixed label.
    assert len(columns) == len(P.DISPLAY_COLUMNS)
    for expected in (P.MARSH_PREMIUM, P.CARRIER_PREMIUM, P.SHARE_OF_WALLET,
                     P.SHARE_OF_PORTFOLIO, P.RANK):
        assert expected in columns


def test_the_answer_carries_more_than_one_chart(warehouse):
    """A performance answer has several things worth showing; one picture hid them."""
    import core.graph.analyst_subgraph as sub

    state = {
        "question": QUESTION, "route": "premium", "flow": "gpr",
        "routing_context": _routing_context(analysis_depth="analytical"),
        "contract": build_contract(detect_operation(QUESTION), allowed_sources=("gpr",)),
        "evidence": [],
    }
    views = sub.positioning_node(state)["chart_plan"]
    charts = [view for view in views[1:] if view.get("chart_data")]

    assert 2 <= len(charts) <= chart_plan.MAX_CHARTS


def test_the_two_chart_ceilings_agree():
    """Which path built the charts must not change how many the reader gets."""
    from core.agents.analyst import chart_picker

    assert chart_picker.MAX_CHARTS == chart_plan.MAX_CHARTS


# --------------------------------------------------------------------------- #
# 5. Presentation — suppressing charts must not suppress the table
# --------------------------------------------------------------------------- #


def _planned_views(question: str, warehouse, **rc_overrides) -> list:
    import core.graph.analyst_subgraph as sub

    state = {
        "question": question, "route": "premium", "flow": "gpr",
        "routing_context": _routing_context(analysis_depth="analytical", **rc_overrides),
        "contract": build_contract(detect_operation(question), allowed_sources=("gpr",)),
        "evidence": [],
    }
    return sub.positioning_node(state).get("chart_plan") or []


def test_table_only_keeps_the_table_and_drops_the_charts(warehouse):
    """The confirmed failure: "table only" deleted the one artifact it asked for."""
    import core.graph.analyst_subgraph as sub
    from core.schemas.routing import OutputDirectives

    rc = _routing_context(
        analysis_depth="analytical",
        output_directives=OutputDirectives(presentation="table_only", charts="none"),
    )
    planned = _planned_views(QUESTION, warehouse)
    out = sub.chart_picker_node(
        {"route": "premium", "question": QUESTION, "routing_context": rc,
         "chart_plan": planned, "evidence": []}
    )

    kept = out["charts"]
    assert [view["tab"] for view in kept] == ["Position"]
    assert all(not chart_plan.is_chart(view) for view in kept)


def test_no_charts_still_leaves_the_evidence_on_screen(warehouse):
    import core.graph.analyst_subgraph as sub
    from core.schemas.routing import OutputDirectives

    rc = _routing_context(
        analysis_depth="analytical",
        output_directives=OutputDirectives(charts="none"),
    )
    out = sub.chart_picker_node(
        {"route": "premium", "question": QUESTION, "routing_context": rc,
         "chart_plan": _planned_views(QUESTION, warehouse), "evidence": []}
    )
    assert out["charts"], "suppressing charts must not empty the evidence panel"


def test_a_normal_turn_keeps_the_table_and_the_charts(warehouse):
    import core.graph.analyst_subgraph as sub

    planned = _planned_views(QUESTION, warehouse)
    out = sub.chart_picker_node(
        {"route": "premium", "question": QUESTION,
         "routing_context": _routing_context(analysis_depth="analytical"),
         "chart_plan": planned, "evidence": []}
    )
    kinds = [chart_plan.is_chart(view) for view in out["charts"]]
    assert kinds[0] is False and any(kinds[1:])


# --------------------------------------------------------------------------- #
# 6. Scope — the table describes the period and the cut that were asked for
# --------------------------------------------------------------------------- #


def test_a_question_with_no_year_is_pinned_to_the_latest(warehouse):
    """Without this the table summed every year in the book into one position."""
    import core.graph.analyst_subgraph as sub

    rc = _routing_context()
    rc.resolved_filters = {
        "Carrier_Group": [scenario.CARRIER], "Country": [scenario.COUNTRY],
    }
    scope = sub.positioning_scope(
        {"question": "Where does Zurich stand in Singapore?", "route": "premium",
         "routing_context": rc}
    )
    assert scope.get("Year") == scenario.CURRENT_YEAR


def test_an_explicit_year_is_left_alone(warehouse):
    import core.graph.analyst_subgraph as sub

    scope = sub.positioning_scope(
        {"question": QUESTION, "route": "premium",
         "routing_context": _routing_context()}
    )
    assert scope["Year"] == [scenario.CURRENT_YEAR]


#: What a `both` route's resolved filters actually look like: the question's
#: entities resolved against BOTH datasets, so every filter arrives twice under
#: two schemas' spellings.
HYBRID_FILTERS = {
    "Carrier_Group": [scenario.CARRIER],
    "Country": [scenario.COUNTRY],
    "Year": [scenario.CURRENT_YEAR],
    "Carrier": [scenario.CARRIER],
    "SurveyCountry": [scenario.COUNTRY],
    "Survey_Year": [scenario.CURRENT_YEAR],
}


def test_a_hybrid_route_still_gets_its_position_table(warehouse):
    """The reported failure: "How is Chubb performance in Singapore for 2025?"
    routed to `both`, and the answer came back with survey commentary and no
    premium table at all.

    Every positioning primitive queries the GPR table. `safe_column` rightly
    raises on `SurveyCountry`, and `build_positioning`'s per-primitive guard
    swallowed all six of those raises as "this column could not be computed" —
    so the pack was empty, the table was dropped, and the log blamed the data.
    """
    import core.graph.analyst_subgraph as sub

    rc = _routing_context()
    rc.resolved_filters = dict(HYBRID_FILTERS)
    state = {
        "question": QUESTION, "route": "both", "flow": "gpr",
        "routing_context": rc,
        "contract": build_contract(detect_operation(QUESTION),
                                   allowed_sources=("gpr", "survey")),
        "evidence": [],
    }
    views = sub.positioning_node(state).get("chart_plan") or []

    assert views, "a hybrid performance turn must still produce the premium table"
    assert views[0]["tab"] == "Position"
    assert views[0]["rows"]


def test_the_survey_spellings_are_dropped_and_the_premium_ones_kept(warehouse):
    """The scope is narrowed, not widened: each dropped column is the survey
    spelling of a premium filter still in place beside it."""
    import core.graph.analyst_subgraph as sub

    rc = _routing_context()
    rc.resolved_filters = dict(HYBRID_FILTERS)
    scope = sub.positioning_scope(
        {"question": QUESTION, "route": "both", "routing_context": rc}
    )
    assert set(scope) == {"Carrier_Group", "Country", "Year"}


def test_a_grouping_the_premium_book_does_not_have_falls_back_to_the_ladder():
    """`detect_group_by` resolves nouns against every flow a `both` route touches."""
    import core.graph.analyst_subgraph as sub
    from core.schemas.routing import QueryIntent

    rc = _routing_context(query_intent=QueryIntent(group_by=["SurveyPractice"]))
    scope = {"Country": scenario.COUNTRY, "Year": scenario.CURRENT_YEAR}
    assert sub.positioning_dimension(
        {"routing_context": rc, "route": "both"}, scope
    ) == "Product_Line"


def test_an_explicit_grouping_decides_the_cut():
    """A stated grouping is a request; the ladder is only the default."""
    import core.graph.analyst_subgraph as sub
    from core.schemas.routing import QueryIntent

    rc = _routing_context(query_intent=QueryIntent(group_by=["SIC_Major_Class"]))
    scope = {"Country": scenario.COUNTRY, "Year": scenario.CURRENT_YEAR}
    assert sub.positioning_dimension({"routing_context": rc, "route": "premium"},
                                     scope) == "SIC_Major_Class"


def test_a_rank_never_appears_without_the_field_it_was_taken_among(warehouse):
    """"#5" alone is meaningless — the glossary says so, and the cell is a number now.

    The field size varies by slice (Marsh places one product with two carriers and
    another with twenty), so it cannot be a sentence under the table. It is a
    column, and it is a number, so it sorts too.
    """
    rows = _planned_views(QUESTION, warehouse)[0]["rows"]
    ranked = [row for row in rows if row[P.RANK] is not None]
    assert ranked, "the fixture must rank at least one slice"
    for row in ranked:
        assert row[P.RANK_FIELD] is not None


def test_the_note_names_the_unit_the_money_columns_are_in(warehouse):
    """The rows are divided by one shared scale; the scale is named once."""
    assert "Premium in" in _planned_views(QUESTION, warehouse)[0]["note"]


def test_the_ladder_still_decides_when_nothing_was_asked_for():
    import core.graph.analyst_subgraph as sub

    scope = {"Country": scenario.COUNTRY, "Year": scenario.CURRENT_YEAR}
    assert sub.positioning_dimension(
        {"routing_context": _routing_context(), "route": "premium"}, scope
    ) == "Product_Line"
