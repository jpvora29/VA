"""End-to-end: a chatbot turn answered by CALLING the analytics library.

This walks the real path the graph node walks — plan + question in, model chooses
tools, the calls are grounded against the registry, the primitives compute over a
real (in-memory) database, and the node writes the same state keys the SQL path
wrote — plus the two decisions that keep it honest:

  * anything the library does not cover clears the coverage key, which routes the
    turn to the existing LLM-SQL path unchanged;
  * every number is checked against the SQL a human would have written.

No credentials and no warehouse: the model is a stub, the engine is in memory.

Run:  pytest tests/test_analytics_tool_path.py -q
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from core.agents.common.analytics_tools import (
    AnalyticsToolRunner,
    LLMToolSelector,
    PlanToolSelector,
    make_tool_selector,
    run_analytics_tools,
)

# ── fixtures ────────────────────────────────────────────────────────────────

ROWS = [
    # carrier,        country,  product,    year, premium
    ("ZURICH GROUP", "Canada", "Property", 2024, 150.0),
    ("ZURICH GROUP", "Canada", "Cyber", 2024, 50.0),
    ("ZURICH GROUP", "Canada", "Property", 2023, 100.0),
    ("AIG", "Canada", "Property", 2024, 200.0),
    ("AIG", "Canada", "Marine", 2024, 80.0),
    ("CHUBB", "Canada", "Property", 2024, 400.0),
    ("ZURICH GROUP", "France", "Property", 2024, 999.0),  # out of scope
]


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(
            text(
                'CREATE TABLE GPR (Carrier_Group TEXT, Country TEXT, Product_Line TEXT, '
                'Year INTEGER, Premium REAL)'
            )
        )
        conn.execute(
            text(
                'INSERT INTO GPR (Carrier_Group, Country, Product_Line, Year, Premium) '
                'VALUES (:cg, :co, :pl, :yr, :pr)'
            ),
            [
                dict(cg=cg, co=co, pl=pl, yr=yr, pr=pr)
                for cg, co, pl, yr, pr in ROWS
            ],
        )
        conn.execute(
            text(
                'CREATE TABLE Peers (Carrier_Group TEXT, Overall_Peer_Group TEXT, Country TEXT)'
            )
        )
        conn.execute(
            text(
                'INSERT INTO Peers (Carrier_Group, Overall_Peer_Group, Country) '
                'VALUES (:cg, :peer, :co)'
            ),
            [
                {"cg": "ZURICH GROUP", "peer": "AIG", "co": "Canada"},
                {"cg": "ZURICH GROUP", "peer": "CHUBB", "co": "Canada"},
            ],
        )
    return eng


_VALUES = {
    "zurich group": ["ZURICH GROUP"],
    "zurich": ["ZURICH GROUP"],
    "canada": ["Canada"],
    "property": ["Property"],
    "cyber": ["Cyber"],
}


def matcher(_flow, _column, term):
    return list(_VALUES.get(str(term).strip().lower(), []))


class FakeLLM:
    """Minimal LangChain-shaped chat model: records the schemas it was bound to."""

    def __init__(self, tool_calls):
        self._tool_calls = tool_calls
        self.bound_schemas = None
        self.calls = 0

    def bind_tools(self, schemas):
        self.bound_schemas = schemas
        return self

    def invoke(self, _messages):
        self.calls += 1
        return SimpleNamespace(tool_calls=list(self._tool_calls))


def runner_with(tool_calls):
    """A runner whose only non-deterministic part — the model — is a stub."""
    return AnalyticsToolRunner(
        selector=LLMToolSelector(llm=FakeLLM(tool_calls)), matcher=matcher
    )


PLAN = json.dumps(
    {
        "intent": "premium by product",
        "metric": "premium",
        "filters": {"Carrier_Group": "ZURICH GROUP", "Country": "Canada"},
        "timeframe": "2024",
    }
)


def state(question="What is Zurich's premium by product in Canada in 2024?", **extra):
    base = {
        "messages": [SimpleNamespace(content=question)],
        "gpr_reasoning": PLAN,
        "routing_context": {"resolved_filters": {}},
    }
    base.update(extra)
    return base


# The node CLEARS its provenance key when the library does not answer, so a value
# left over from an earlier turn in the same conversation cannot misroute this one.
UNCOVERED = {"gpr_analytics": None}


def sql_value(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


# ── the covered path ────────────────────────────────────────────────────────


def test_turn_is_answered_by_calling_the_library(engine):
    update = run_analytics_tools(
        state(),
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}}]
        ),
        engine=engine,
    )

    assert update["gpr_query_result"] == [
        {"Product_Line": "Property", "Premium": 150.0},
        {"Product_Line": "Cyber", "Premium": 50.0},
    ]
    assert update["gpr_sql_error"] is False
    assert update["gpr_overflow"] is False


def test_numbers_match_the_sql_a_human_would_write(engine):
    update = run_analytics_tools(
        state(),
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}}]
        ),
        engine=engine,
    )
    expected = sql_value(
        engine,
        'SELECT SUM(Premium) FROM GPR WHERE Carrier_Group = :c AND Country = :co '
        'AND Year = :y AND Product_Line = :p',
        c="ZURICH GROUP",
        co="Canada",
        y=2024,
        p="Property",
    )
    property_row = next(
        row for row in update["gpr_query_result"] if row["Product_Line"] == "Property"
    )
    assert property_row["Premium"] == expected


def test_scope_is_applied_without_the_model_being_asked_for_it(engine):
    fake = FakeLLM([{"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}}])
    runner = AnalyticsToolRunner(selector=LLMToolSelector(llm=fake), matcher=matcher)
    update = run_analytics_tools(state(), flow="gpr", runner=runner, engine=engine)

    # The 2023 row and the France row are out of scope, and the model never named
    # a filter: carrier / country / year came from the plan, deterministically.
    assert update["gpr_analytics"]["scope"] == {
        "Carrier_Group": "ZURICH GROUP",
        "Country": "Canada",
        "Year": 2024,
    }
    assert all(row["Premium"] < 999.0 for row in update["gpr_query_result"])


def test_provenance_records_the_calculations_not_a_query(engine):
    update = run_analytics_tools(
        state(),
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}}]
        ),
        engine=engine,
    )
    assert "compute_breakdown" in update["gpr_sql_query"]
    assert update["gpr_sql_query"].startswith("--")
    facts = update["gpr_analytics"]["facts"]
    assert facts and all(fact["formula"] for fact in facts)


def test_several_calls_fold_into_one_comparable_table(engine):
    update = run_analytics_tools(
        state("How does Zurich's premium compare with peers in Canada in 2024?"),
        flow="gpr",
        runner=runner_with(
            [
                {"name": "compute_breakdown", "args": {}},
                {"name": "compute_peer_average_total", "args": {}},
            ]
        ),
        engine=engine,
    )
    row = update["gpr_query_result"][0]
    # Zurich's own book, and the average of its peers' totals (AIG 280, CHUBB 400).
    assert row["Premium"] == 200.0
    assert row["Peer_Avg_Premium"] == pytest.approx(340.0)


def test_repeated_runs_return_identical_numbers(engine):
    calls = [{"name": "compute_share_of_portfolio", "args": {"group_by": ["Product_Line"]}}]
    first = run_analytics_tools(state(), flow="gpr", runner=runner_with(calls), engine=engine)
    second = run_analytics_tools(state(), flow="gpr", runner=runner_with(calls), engine=engine)
    assert first["gpr_query_result"] == second["gpr_query_result"]


def test_pinned_peers_override_the_peers_table(engine):
    pinned = {
        "custom_peers": {"flow": "gpr", "carrier": "ZURICH GROUP", "peers": ["CHUBB"]},
        "custom_peers_active": True,
    }
    update = run_analytics_tools(
        state(**pinned),
        flow="gpr",
        runner=runner_with([{"name": "compute_peer_average_total", "args": {}}]),
        engine=engine,
    )
    # CHUBB alone (400), not the AIG+CHUBB group average (340).
    assert update["gpr_query_result"][0]["Peer_Avg_Premium"] == pytest.approx(400.0)


# ── the fallback path (the SQL agent still owns everything else) ─────────────


def test_no_tool_call_falls_back_to_sql(engine):
    assert run_analytics_tools(
        state("List every client Zurich wrote last year"),
        flow="gpr",
        runner=runner_with([]),
        engine=engine,
    ) == UNCOVERED


def test_a_hallucinated_column_falls_back_instead_of_guessing(engine):
    assert run_analytics_tools(
        state(),
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Underwriter"]}}]
        ),
        engine=engine,
    ) == UNCOVERED


def test_a_partly_runnable_selection_falls_back_whole(engine):
    # One good call, one unusable: half an answer presented as a whole one is the
    # failure this path exists to remove.
    assert run_analytics_tools(
        state(),
        flow="gpr",
        runner=runner_with(
            [
                {"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}},
                {"name": "compute_nps", "args": {}},  # survey-only
            ]
        ),
        engine=engine,
    ) == UNCOVERED


def test_an_unresolvable_filter_value_falls_back(engine):
    plan = json.dumps({"metric": "premium", "filters": {"Country": "Atlantis"}})
    assert run_analytics_tools(
        state(gpr_reasoning=plan),
        flow="gpr",
        runner=runner_with([{"name": "compute_breakdown", "args": {}}]),
        engine=engine,
    ) == UNCOVERED


def test_the_flag_restores_the_pure_sql_path(engine, monkeypatch):
    monkeypatch.setenv("ANALYTICS_TOOLS", "off")
    assert run_analytics_tools(
        state(),
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}}]
        ),
        engine=engine,
    ) == UNCOVERED
    assert make_tool_selector() is None


# ── selection strategies ────────────────────────────────────────────────────


def test_a_plan_that_names_its_primitives_needs_no_model_call(engine):
    plan = json.dumps(
        {
            "metric": "premium",
            "filters": {"Carrier_Group": "ZURICH GROUP", "Country": "Canada"},
            "timeframe": "2024",
            "primitives": [
                {"name": "compute_breakdown", "group_by": ["Product_Line"]}
            ],
        }
    )
    fake = FakeLLM([])  # would return nothing if it were consulted
    runner = AnalyticsToolRunner(
        selector=make_tool_selector("on", llm=fake), matcher=matcher
    )
    update = run_analytics_tools(
        state(gpr_reasoning=plan), flow="gpr", runner=runner, engine=engine
    )
    assert update["gpr_query_result"]
    assert fake.calls == 0


def test_plan_mode_never_calls_a_model():
    selector = make_tool_selector("plan")
    assert isinstance(selector, PlanToolSelector)


def test_the_model_is_bound_to_this_flows_tools_only(engine):
    fake = FakeLLM([{"name": "compute_breakdown", "args": {}}])
    runner = AnalyticsToolRunner(selector=LLMToolSelector(llm=fake), matcher=matcher)
    run_analytics_tools(state(), flow="gpr", runner=runner, engine=engine)
    names = {schema["function"]["name"] for schema in fake.bound_schemas}
    assert "compute_share_of_wallet" in names
    assert "compute_nps" not in names  # survey-only definition, not offered here


# ── the survey flow uses the same node ──────────────────────────────────────


@pytest.fixture
def survey_engine():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(
            text(
                'CREATE TABLE Carriers (Carrier TEXT, SurveyCountry TEXT, Section TEXT, '
                'Survey_Year INTEGER, Score REAL)'
            )
        )
        conn.execute(
            text(
                'INSERT INTO Carriers (Carrier, SurveyCountry, Section, Survey_Year, Score) '
                'VALUES (:c, :co, :s, :y, :sc)'
            ),
            [
                {"c": "Zurich", "co": "Canada", "s": "Claims", "y": 2024, "sc": 8.0},
                {"c": "Zurich", "co": "Canada", "s": "Service", "y": 2024, "sc": 6.0},
            ],
        )
    return eng


def test_survey_turn_writes_survey_state_keys(survey_engine):
    plan = json.dumps({"metric": "score", "filters": {"Carrier": "Zurich"}, "timeframe": "2024"})
    survey_matcher = lambda _f, _c, term: (
        ["Zurich"] if str(term).lower() == "zurich" else []
    )
    runner = AnalyticsToolRunner(
        selector=LLMToolSelector(
            llm=FakeLLM(
                [{"name": "compute_attribute_breakdown", "args": {"group_by": ["Section"]}}]
            )
        ),
        matcher=survey_matcher,
    )
    update = run_analytics_tools(
        {
            "messages": [SimpleNamespace(content="How is Zurich perceived by section?")],
            "survey_reasoning": plan,
        },
        flow="survey",
        runner=runner,
        engine=survey_engine,
    )
    assert update["survey_query_result"] == [
        {"Section": "Claims", "Score": 8.0},
        {"Section": "Service", "Score": 6.0},
    ]
    assert update["survey_sql_error"] is False
    assert "compute_attribute_breakdown" in update["survey_analytics"]["calls"][0]


# ── the router contract ─────────────────────────────────────────────────────


def test_a_previous_turn_cannot_misroute_the_next_one(engine):
    """Graph state is checkpointed per conversation: coverage must be re-decided."""
    from core.agents.common.analytics_tools import analytics_covered

    covered = run_analytics_tools(
        state(),
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}}]
        ),
        engine=engine,
    )
    assert analytics_covered(covered, "gpr")

    # Same conversation, a question the library does not cover.
    carried_over = {**state(), **covered}
    uncovered = run_analytics_tools(
        carried_over, flow="gpr", runner=runner_with([]), engine=engine
    )
    assert analytics_covered({**carried_over, **uncovered}, "gpr") is False


# ── the latest-year default ─────────────────────────────────────────────────
#
# The flows' timeframe skills have always said: when the query names no period,
# answer for the latest year, never an all-years aggregate. `turn_scope` only reads
# a literal four-digit year out of the plan, so before this a blank timeframe — and
# a relative one like "latest year" — silently summed every year in the book.


def _scope_year(engine, question, timeframe=""):
    """The Year the scope ends up pinned to for a question, or None if unpinned."""
    from core.agents.common.analytics_tools import _pin_latest_year
    from core.analytics.tools import turn_scope

    scope = turn_scope(
        "gpr",
        resolved_filters={"Carrier_Group": ["ZURICH GROUP"]},
        timeframe=timeframe,
    )
    return _pin_latest_year(
        "gpr", scope, user_query=question, engine=engine
    ).filters.get("Year")


def test_a_question_naming_no_period_defaults_to_the_latest_year(engine):
    assert _scope_year(engine, "What is Zurich's premium in Canada?") == 2024


def test_a_relative_latest_timeframe_pins_the_latest_year(engine):
    """The planner writing "latest year" used to leave the scope wide open, because
    `years_in` finds no digits in it — the worst case, since the planner got it right."""
    assert _scope_year(engine, "Zurich premium latest year", "latest year") == 2024
    assert _scope_year(engine, "Zurich premium, most recent", "most recent") == 2024


def test_an_explicit_year_is_never_overridden(engine):
    assert _scope_year(engine, "Zurich premium in 2023", "2023") == 2023


@pytest.mark.parametrize(
    "question",
    [
        "Zurich premium YoY",
        "premium growth for Zurich",
        "Zurich premium trend across years",
        "Zurich premium last year",
        "rolling 12 months for Zurich",
        "Zurich premium in Q2",
    ],
)
def test_a_multi_period_question_is_left_unpinned(engine, question):
    """Pinning one year would break every one of these: they need more than one."""
    assert _scope_year(engine, question) is None


def test_the_default_reads_the_data_not_a_hard_coded_year(engine):
    """Load one more year and the default follows it — no list to keep in sync."""
    with engine.begin() as conn:
        conn.execute(
            text('INSERT INTO GPR (Carrier_Group, Country, Product_Line, Year, Premium) '
                 'VALUES (:cg, :co, :pl, :yr, :pr)'),
            dict(cg="ZURICH GROUP", co="Canada", pl="Property", yr=2025, pr=10.0),
        )
    assert _scope_year(engine, "What is Zurich's premium in Canada?") == 2025


def test_the_default_respects_the_rest_of_the_scope(engine):
    """A carrier with no rows has no latest year, so nothing is pinned rather than
    a year borrowed from somebody else's book."""
    from core.agents.common.analytics_tools import _pin_latest_year
    from core.analytics.tools import TurnScope

    scope = TurnScope(filters={"Carrier_Group": "NOBODY"})
    pinned = _pin_latest_year("gpr", scope, user_query="premium", engine=engine)
    assert "Year" not in pinned.filters


def test_the_answer_is_one_year_not_every_year(engine):
    """The end of the bug: a bare question must not fold 2023 and 2024 together."""
    runner = runner_with([{"name": "compute_breakdown", "args": {"metric": "premium"}}])
    update = run_analytics_tools(
        state(question="What is Zurich's premium in Canada?",
              gpr_reasoning=json.dumps({"metric": "premium", "filters": {
                  "Carrier_Group": "ZURICH GROUP", "Country": "Canada"}, "timeframe": ""})),
        flow="gpr",
        runner=runner,
        engine=engine,
    )
    rows = update["gpr_query_result"]
    total = sum(float(r[c]) for r in rows for c in r if str(c).lower() == "premium")
    only_2024 = sql_value(
        engine,
        'SELECT SUM(Premium) FROM GPR WHERE Carrier_Group = :cg AND Country = :co '
        'AND Year = 2024',
        cg="ZURICH GROUP", co="Canada",
    )
    assert total == pytest.approx(only_2024)      # 200.0, not 300.0


def test_the_turn_states_the_year_it_defaulted_to(engine):
    """The timeframe skill requires the answer to name the year it fell back to. A
    silent default is worse than none — the reader cannot tell 2024 from all-time."""
    runner = runner_with([{"name": "compute_breakdown", "args": {"metric": "premium"}}])
    update = run_analytics_tools(
        state(question="What is Zurich's premium in Canada?",
              gpr_reasoning=json.dumps({"metric": "premium", "filters": {
                  "Carrier_Group": "ZURICH GROUP", "Country": "Canada"}, "timeframe": ""})),
        flow="gpr",
        runner=runner,
        engine=engine,
    )
    # The plan the writer receives now carries the resolved year.
    assert json.loads(update["gpr_reasoning"])["timeframe"] == "2024"
    assert update["gpr_analytics"]["scope"]["Year"] == 2024
    # And the displayed provenance shows the scope the numbers were computed under.
    assert "'Year': 2024" in update["gpr_sql_query"]


def test_an_explicitly_dated_turn_leaves_the_plan_alone(engine):
    """Nothing was defaulted, so nothing is rewritten."""
    runner = runner_with([{"name": "compute_breakdown", "args": {"metric": "premium"}}])
    plan = json.dumps({"metric": "premium", "filters": {
        "Carrier_Group": "ZURICH GROUP", "Country": "Canada"}, "timeframe": "2023"})
    update = run_analytics_tools(
        state(question="What is Zurich's premium in Canada in 2023?", gpr_reasoning=plan),
        flow="gpr",
        runner=runner,
        engine=engine,
    )
    assert "gpr_reasoning" not in update


# ── peer confidentiality ────────────────────────────────────────────────────
#
# This node writes `gpr_query_result` WITHOUT going through `gpr_execute_sql`,
# and the library answers whenever it covers the question — so for many turns
# this, not the SQL path, is what fills the table and the chart the user sees.
# It therefore has to close the same confidentiality boundary.


def test_a_carrier_cut_names_no_individual_carrier(engine):
    """A market-wide cut used to hand the UI a list of real carrier names."""
    plan = json.dumps({"metric": "premium", "filters": {"Country": "Canada"},
                       "timeframe": "2024"})
    update = run_analytics_tools(
        state(question="Premium by carrier in Canada in 2024.", gpr_reasoning=plan),
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Carrier_Group"]}}]
        ),
        engine=engine,
    )
    shown = [row["Carrier_Group"] for row in update["gpr_query_result"]]
    assert not ({"ZURICH GROUP", "AIG", "CHUBB"} & set(shown))
    assert all(name.startswith("Peer ") for name in shown)


def test_redaction_does_not_disturb_the_figures(engine):
    """Anonymised, not aggregated — the premium column is untouched."""
    plan = json.dumps({"metric": "premium", "filters": {"Country": "Canada"},
                       "timeframe": "2024"})
    kwargs = dict(
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Carrier_Group"]}}]
        ),
        engine=engine,
    )
    update = run_analytics_tools(
        state(question="Premium by carrier in Canada in 2024.", gpr_reasoning=plan),
        **kwargs,
    )
    # Canada 2024: Zurich 150+50, AIG 200+80, Chubb 400.
    assert sorted(r["Premium"] for r in update["gpr_query_result"]) == [200.0, 280.0, 400.0]


def test_a_non_carrier_cut_is_untouched(engine):
    """Redaction must not reach into an ordinary breakdown."""
    update = run_analytics_tools(
        state(),
        flow="gpr",
        runner=runner_with(
            [{"name": "compute_breakdown", "args": {"group_by": ["Product_Line"]}}]
        ),
        engine=engine,
    )
    assert update["gpr_query_result"] == [
        {"Product_Line": "Property", "Premium": 150.0},
        {"Product_Line": "Cyber", "Premium": 50.0},
    ]
