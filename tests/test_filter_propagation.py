"""Carrier, country and period: the same three filters, everywhere they are used.

The reported failure: "What is Zurich premium in Canada for the year 2025?" was
answered with every year in the book added together, and neither the prose nor the
table said so. The year the reader typed reached nothing.

The cause was one gap, but the class of bug is the important thing. A turn's
filters are resolved once and then read by eight or nine independent consumers —
the tool scope, the schema slice the solvers ground against, the positioning pack,
the scope chips the reader sees, the mandatory-filter gate. Any one of them
quietly dropping a filter produces a confident answer about the wrong data, and
nothing on screen says which.

So these tests walk ONE turn's filters through every consumer that can be run
without a model, and assert all of them agree. A new consumer that forgets a
filter fails here rather than in production.

Run:  pytest tests/test_filter_propagation.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.agents.common.contract import resolve_entities, resolved_filters_of
from core.analytics.tools.scope import turn_scope
from core.schemas.routing import QueryEntities, RoutingContext
from tests.evaluation import scenario
from tests.evaluation.warehouse import build_engine

QUESTION = "What is Zurich premium in Canada for the year 2025?"

#: The three roles every consumer must preserve, and the GPR column each lands on.
CARRIER_COLUMN = "Carrier_Group"
COUNTRY_COLUMN = "Country"
YEAR_COLUMN = "Year"


@pytest.fixture(scope="module")
def engine():
    return build_engine()


@pytest.fixture
def warehouse(engine, monkeypatch):
    from core.initialization import Initialization

    monkeypatch.setattr(Initialization, "engine", engine)
    return engine


def _entities() -> QueryEntities:
    """What the context filler extracts from `QUESTION`."""
    return QueryEntities(carriers=["Zurich"], countries=["Canada"], years=["2025"])


@pytest.fixture
def resolved() -> dict:
    filters, unresolved = resolve_entities(_entities(), "premium")
    assert not unresolved, f"nothing in this question should fail to resolve: {unresolved}"
    return filters


def _routing_context(resolved: dict) -> RoutingContext:
    rc = RoutingContext(table_family="premium", intent_type="new_question")
    rc.entities = _entities()
    rc.resolved_filters = resolved
    rc.analysis_depth = "analytical"
    return rc


# --------------------------------------------------------------------------- #
# 1. Extraction — all three roles become filters
# --------------------------------------------------------------------------- #


def test_the_contract_resolves_all_three_filters(resolved):
    """The year used to be dropped here: the entity loop has no `years` kind and
    the year column is a DATE column, not one of the registry's entity columns."""
    assert resolved.get(CARRIER_COLUMN) == [scenario.CARRIER]
    assert resolved.get(COUNTRY_COLUMN) == ["Canada"]
    assert resolved.get(YEAR_COLUMN) == ["2025"]


@pytest.mark.parametrize("mention, expected", [
    ("2025", ["2025"]),
    ("FY2025", ["2025"]),
    ("2025.", ["2025"]),
    ("the year 2025", ["2025"]),
    ("", []),
    ("latest", []),
    ("Q1", []),
])
def test_a_year_is_read_not_fuzzy_matched(mention, expected):
    """"2025" against a column holding 2024 and 2025 is a similarity question with
    a right answer that has nothing to do with similarity."""
    from core.agents.common.contract import resolve_years

    assert resolve_years([mention]) == expected


def test_the_survey_flow_gets_the_year_on_its_own_column():
    """Each flow spells the period differently (`Year` / `Survey_Year`), so the
    filter lands per flow rather than on one hard-coded name."""
    filters, _unresolved = resolve_entities(
        QueryEntities(carriers=["Zurich"], years=["2025"]), "survey"
    )
    assert filters.get("Survey_Year") == ["2025"]
    assert YEAR_COLUMN not in filters


def test_a_hybrid_route_resolves_the_period_for_both_flows():
    """A `both` turn queries two schemas, so it needs the filter in both
    spellings — and the premium path narrows back to its own
    (`analyst_subgraph.gpr_filters`) before it queries."""
    filters, _unresolved = resolve_entities(
        QueryEntities(carriers=["Zurich"], countries=["Canada"], years=["2025"]),
        "both",
    )
    assert filters.get(YEAR_COLUMN) == ["2025"]
    assert filters.get("Survey_Year") == ["2025"]


def test_the_premium_path_narrows_a_hybrid_scope_to_its_own_columns():
    import core.graph.analyst_subgraph as sub

    filters, _unresolved = resolve_entities(
        QueryEntities(carriers=["Zurich"], countries=["Canada"], years=["2025"]),
        "both",
    )
    narrowed = sub.gpr_filters(filters, state={"route": "both"})
    assert YEAR_COLUMN in narrowed and COUNTRY_COLUMN in narrowed
    assert "Survey_Year" not in narrowed and "SurveyCountry" not in narrowed


def test_an_unresolvable_carrier_is_still_reported(warehouse):
    """Dropping a filter silently is the failure; saying so is the requirement."""
    _filters, unresolved = resolve_entities(
        QueryEntities(carriers=["Notacarrier"], countries=["Canada"]), "premium"
    )
    assert [u.term for u in unresolved] == ["Notacarrier"]


# --------------------------------------------------------------------------- #
# 2. The tool scope — what the primitives are actually filtered by
# --------------------------------------------------------------------------- #


def test_the_tool_scope_carries_all_three(resolved):
    scope = turn_scope("gpr", resolved_filters=resolved, timeframe="2025")
    assert scope.filters[CARRIER_COLUMN] == scenario.CARRIER
    assert scope.filters[COUNTRY_COLUMN] == "Canada"
    assert str(scope.filters[YEAR_COLUMN]) == "2025"


def test_the_year_survives_a_planner_that_omitted_its_timeframe(resolved):
    """The planner's `timeframe` is a model field. It was the ONLY route the year
    had into the scope, so when it was blank the turn widened to all years."""
    scope = turn_scope("gpr", resolved_filters=resolved, timeframe="")
    assert str(scope.filters[YEAR_COLUMN]) == "2025"


def test_the_question_itself_is_the_last_resort_for_the_period():
    """Every source above this one is written by a model. This one cannot be."""
    scope = turn_scope("gpr", resolved_filters={}, timeframe="", user_query=QUESTION)
    assert scope.filters[YEAR_COLUMN] == 2025


def test_a_solver_that_forgot_the_year_still_gets_it(warehouse):
    """The analyst path's version of the same hole.

    Each solver writes its own tool-call filters; the turn's resolved values are
    only a PREFERENCE in its prompt. `pin_latest_year` was the backstop, and it
    bailed out on any timeframe reference at all — so a question naming a year,
    whose solver then omitted it, got no period and no default.
    """
    from core.analytics.tools.scope import pin_latest_year

    filters, defaulted = pin_latest_year(
        "gpr", {"Carrier_Group": scenario.CARRIER}, user_query=QUESTION,
        engine=warehouse,
    )
    assert filters[YEAR_COLUMN] == 2025
    assert defaulted is None, "a year the reader stated is not a default to disclose"


def test_a_trend_question_is_still_left_alone(warehouse):
    """A trend needs more than one year; pinning one answers a narrower question."""
    from core.analytics.tools.scope import pin_latest_year

    filters, _defaulted = pin_latest_year(
        "gpr", {}, user_query="Show the premium trend since 2020", engine=warehouse,
    )
    assert YEAR_COLUMN not in filters


def test_a_question_naming_no_year_still_defaults_and_discloses(warehouse):
    """The existing rule must survive: choose the latest year, and SAY so."""
    from core.analytics.tools.scope import pin_latest_year

    filters, defaulted = pin_latest_year(
        "gpr", {"Carrier_Group": scenario.CARRIER},
        user_query="What is Zurich premium?", engine=warehouse,
    )
    assert filters[YEAR_COLUMN] == defaulted == scenario.CURRENT_YEAR


def test_a_question_naming_no_year_pins_nothing_here():
    """The floor must not invent a period — that is `pin_latest_year`'s job, and
    it is the one that records the default so the answer can disclose it."""
    scope = turn_scope("gpr", resolved_filters={}, timeframe="",
                       user_query="What is Zurich premium in Canada?")
    assert YEAR_COLUMN not in scope.filters


def test_the_contract_beats_a_plan_filter_on_the_same_column(resolved):
    """The documented precedence: the contract's values are the ones the user
    confirmed, so a planner guess on the same column does not displace them. (A
    single CALL's own filters still win, one level further down, in the
    orchestrator's per-call merge — that is what a comparison year rides on.)"""
    scope = turn_scope("gpr", resolved_filters=resolved,
                       plan_filters={"Year": 2024}, timeframe="")
    assert str(scope.filters[YEAR_COLUMN]) == "2025"


# --------------------------------------------------------------------------- #
# 3. The number — the filters have to change the answer
# --------------------------------------------------------------------------- #


def test_the_year_filter_changes_the_figure(warehouse):
    """The proof the bug mattered: without the year this question answered with
    every year in the book added together, and said nothing about it.

    Uses the scenario's own carrier and country so there are real rows behind
    both figures — a comparison of two zeroes would pass while proving nothing.
    """
    from core.analytics.library import compute_market_presence
    from core.analytics.types import PrimitiveArgs

    def premium(filters):
        facts = compute_market_presence(
            PrimitiveArgs(flow="gpr", metric="premium", filters=filters),
            engine=warehouse,
        )
        return facts[0].value if facts else None

    entities = QueryEntities(
        carriers=[scenario.CARRIER], countries=[scenario.COUNTRY],
        years=[str(scenario.CURRENT_YEAR)],
    )
    filters, _unresolved = resolve_entities(entities, "premium")
    scoped = turn_scope("gpr", resolved_filters=filters, timeframe="").filters
    all_years = {k: v for k, v in scoped.items() if k != YEAR_COLUMN}

    one_year, every_year = premium(scoped), premium(all_years)
    assert one_year, "the fixture must hold rows for this scope"
    assert one_year < every_year, (
        "one year must be less than every year, or the filter did nothing"
    )


# --------------------------------------------------------------------------- #
# 4. Every other consumer of the turn's filters
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 3b. A cut the scope already pins is not a cut
# --------------------------------------------------------------------------- #


def test_a_group_by_the_scope_already_pins_is_dropped():
    """"Share of wallet for Property, by product line" is one row reading
    "Property". The reader asked for a figure and got a one-row table of it."""
    from core.analytics.orchestrator import useful_group_by

    assert useful_group_by(("Product_Line",), {"Product_Line": "Property"}) == ()
    assert useful_group_by(("Product_Line",), {"Product_Line": ["Property"]}) == ()


def test_a_cut_the_scope_does_not_pin_survives():
    from core.analytics.orchestrator import useful_group_by

    assert useful_group_by(
        ("SIC_Major_Class",), {"Product_Line": "Property"}
    ) == ("SIC_Major_Class",)
    # Two values is still a comparison worth cutting by.
    assert useful_group_by(
        ("Product_Line",), {"Product_Line": ["Property", "Cyber"]}
    ) == ("Product_Line",)


def test_the_reported_question_returns_a_figure_not_a_one_row_table(warehouse):
    """"What is Zurich's Share of Wallet for Property" — the answer is a number."""
    from core.analytics.orchestrator import AnalyticsOrchestrator

    scope = {
        "Carrier_Group": scenario.CARRIER, "Country": scenario.COUNTRY,
        "Year": scenario.CURRENT_YEAR, "Product_Line": "Property",
    }
    evidence = AnalyticsOrchestrator().run(
        [{"name": "compute_share_of_wallet", "metric": "premium",
          "group_by": ["Product_Line"]}],
        flow="gpr", shared_filters=scope, engine=warehouse,
        subject=scenario.CARRIER,
    )
    assert len(evidence.facts) == 1
    assert "Product_Line" not in evidence.facts[0].dims


def test_a_pinned_product_cuts_the_table_by_industry_not_product(warehouse):
    """The next level DOWN, and Major before Minor — the ladder's whole job."""
    from core.analytics.dimensions import choose_dimension

    filters, _unresolved = resolve_entities(
        QueryEntities(carriers=["Zurich"], products=["Property"]), "premium"
    )
    assert choose_dimension(filters, flow="gpr") == "SIC_Major_Class"


def test_a_pinned_industry_steps_down_to_sub_industry():
    from core.analytics.dimensions import choose_dimension

    assert choose_dimension(
        {"Product_Line": "Property", "SIC_Major_Class": "Manufacturing"}, flow="gpr"
    ) == "SIC_Minor_Class"


def test_the_routing_context_round_trips_all_three(resolved):
    """`resolved_filters_of` is what most consumers read. It must lose nothing."""
    out = resolved_filters_of(_routing_context(resolved))
    assert set(out) == {CARRIER_COLUMN, COUNTRY_COLUMN, YEAR_COLUMN}


def test_the_schema_slice_the_solvers_ground_against_keeps_them(resolved):
    """With no model configured the identifier degrades — and the contract's
    values must survive that, because the solvers filter on them."""
    from core.agents.analyst.schema_identifier import identify_schema

    slice_ = identify_schema(
        question=QUESTION, sub_questions=[QUESTION], flow="gpr",
        pre_resolved=resolved,
    )
    for column in (CARRIER_COLUMN, COUNTRY_COLUMN, YEAR_COLUMN):
        assert column in slice_.resolved_values, f"{column} lost in the schema slice"


def test_the_positioning_table_is_computed_under_the_same_filters(warehouse, resolved):
    import core.graph.analyst_subgraph as sub

    scope = sub.positioning_scope({
        "question": QUESTION, "route": "premium",
        "routing_context": _routing_context(resolved),
    })
    assert scope[CARRIER_COLUMN] == [scenario.CARRIER]
    assert scope[COUNTRY_COLUMN] == ["Canada"]
    assert scope[YEAR_COLUMN] == ["2025"]


def test_the_reader_can_see_all_three_as_chips(resolved):
    """A filter the reader cannot see is a filter they cannot check. The period
    chip was missing for exactly as long as the period filter was."""
    from core.answers.scope import answer_scope

    chips = dict(answer_scope({"routing_context": _routing_context(resolved)}))
    assert chips.get("carrier") == scenario.CARRIER
    assert chips.get("country") == "Canada"
    assert chips.get("period") == "2025"


def test_the_mandatory_filter_gate_sees_a_scoped_turn(resolved):
    """A fully-specified question must never be stopped to be asked for scope."""
    from core.agents.common.mandatory_filters import MandatoryFilterGate

    gate = MandatoryFilterGate()
    rc = _routing_context(resolved)
    assert gate.has_scope(rc) is True
    assert gate.missing_mandatory_filters(rc) == []


def test_an_unscoped_question_is_still_gated():
    """The gate must stay useful — this is the case it exists for."""
    from core.agents.common.mandatory_filters import MandatoryFilterGate

    rc = RoutingContext(table_family="premium", intent_type="new_question")
    rc.entities = QueryEntities()
    rc.resolved_filters = {}
    assert MandatoryFilterGate().has_scope(rc) is False
