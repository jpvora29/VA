"""The period a model-written query answers for, and whether it matches the insight.

The reported failure: ask a question that names no year, and the answer's prose is
written for the latest year in the data — every path that builds its own filters
pins one — while the TABLE under it is the result of a query a model wrote, which
forgot to say when and therefore summed every year in the book. Two numbers for the
same question, one above the other.

These tests walk the rule that closes it (`core.analytics.sql_period`) from the
text edit out to the rows a reader sees:

    the rewrite  ->  what it refuses  ->  when it fires  ->  the year the rows
    land on  ->  the solver's own tool  ->  a slice whose data ends early

The later sections run the rewritten query against `tests.evaluation`'s warehouse,
whose schema mirrors `flows.yaml`, and compare the rows with the year the pinning
helper the INSIGHT goes through would have chosen. A guard that produces valid SQL
but a different year from the prose would pass every unit test here and still ship
the bug.

Run:  pytest tests/test_sql_period_guard.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.analytics.sql_period import (
    latest_year_in,
    mentions_column,
    scope_sql_to_default_year,
    scope_to_year,
    unsafe_reason,
)
from core.analytics.tools.scope import pin_latest_year
from tests.evaluation import scenario
from tests.evaluation.warehouse import build_engine

UNTIMED = "What is Zurich's premium in Singapore?"
TIMED = "What was Zurich's premium in Singapore in 2024?"

BARE = 'SELECT SUM(Premium) AS premium FROM "GPR"'
FILTERED = (
    'SELECT SUM(Premium) AS premium FROM "GPR" '
    "WHERE Carrier_Group = 'ZURICH GROUP' AND Country = 'Singapore'"
)
GROUPED = (
    'SELECT Product_Line, SUM(Premium) AS premium FROM "GPR" '
    "WHERE Carrier_Group = 'ZURICH GROUP' "
    "GROUP BY Product_Line ORDER BY premium DESC LIMIT 10"
)


@pytest.fixture(scope="module")
def engine():
    return build_engine()


@pytest.fixture
def warehouse(engine, monkeypatch):
    """Point the primitives' default engine at the fixture warehouse."""
    from core.initialization import Initialization

    monkeypatch.setattr(Initialization, "engine", engine)
    return engine


# --------------------------------------------------------------------------- #
# 1. The rewrite — a period added without changing what else the query means
# --------------------------------------------------------------------------- #


def test_a_query_with_no_where_gets_one():
    assert scope_to_year(BARE, "Year", 2025) == (
        'SELECT SUM(Premium) AS premium FROM "GPR" WHERE "Year" = 2025'
    )


def test_an_existing_where_is_kept_and_narrowed():
    scoped = scope_to_year(FILTERED, "Year", 2025)
    assert "Carrier_Group = 'ZURICH GROUP'" in scoped
    assert "Country = 'Singapore'" in scoped
    assert '"Year" = 2025' in scoped


def test_the_predicate_lands_before_group_by():
    scoped = scope_to_year(GROUPED, "Year", 2025)
    assert scoped.index('"Year" = 2025') < scoped.index("GROUP BY")
    assert scoped.endswith("ORDER BY premium DESC LIMIT 10")


def test_an_or_condition_is_wrapped_before_the_period_is_added():
    """The one mistake this rewrite could plausibly make.

    `WHERE a OR b AND Year = 2025` is not `WHERE (a OR b) AND Year = 2025` — AND
    binds tighter — so appending the predicate bare would silently widen the query
    to every year for one of the two branches.
    """
    sql = 'SELECT SUM(Premium) FROM "GPR" WHERE Country = \'Singapore\' OR Country = \'Malaysia\''
    scoped = scope_to_year(sql, "Year", 2025)
    assert "WHERE (Country = 'Singapore' OR Country = 'Malaysia') AND \"Year\" = 2025" in scoped


def test_a_trailing_semicolon_survives():
    assert scope_to_year(BARE + ";", "Year", 2025).endswith("2025;")


# --------------------------------------------------------------------------- #
# 2. What it refuses — a decline costs nothing, a bad rewrite costs the answer
# --------------------------------------------------------------------------- #


def test_a_query_that_already_names_the_year_is_left_alone():
    sql = FILTERED + " AND Year = 2024"
    assert scope_to_year(sql, "Year", 2025) is None


def test_a_query_that_groups_by_year_is_left_alone():
    """It said something about the period. Narrowing it answers a different question."""
    sql = 'SELECT Year, SUM(Premium) FROM "GPR" GROUP BY Year'
    assert scope_to_year(sql, "Year", 2025) is None


@pytest.mark.parametrize(
    "sql, expected",
    [
        ('WITH x AS (SELECT 1) SELECT * FROM x', "a common table expression"),
        ('SELECT 1 FROM "GPR" UNION SELECT 2 FROM "GPR"', "a set operation"),
        ('SELECT * FROM "GPR" JOIN "Peers" ON 1 = 1', "a join"),
        ('SELECT SUM(x) OVER (PARTITION BY a) FROM "GPR"', "a window function"),
        ('SELECT * FROM "GPR" WHERE a IN (SELECT b FROM "Peers")', "a subquery"),
        ('SELECT 1; SELECT 2', "more than one statement"),
    ],
)
def test_the_shapes_it_will_not_touch(sql, expected):
    assert unsafe_reason(sql) == expected
    assert scope_to_year(sql, "Year", 2025) is None


def test_a_year_column_of_another_flow_is_not_a_match():
    """`Survey_Year` must not read as the GPR `Year` column, or vice versa."""
    assert mentions_column('SELECT Survey_Year FROM "Carriers"', "Year") is False
    assert mentions_column('SELECT Survey_Year FROM "Carriers"', "Survey_Year") is True


# --------------------------------------------------------------------------- #
# 3. The rule — only a turn that named no period, and only a column-free query
# --------------------------------------------------------------------------- #


def test_a_question_naming_a_year_is_left_alone(warehouse):
    scoped, year = scope_sql_to_default_year(
        "gpr", FILTERED, question=TIMED, engine=warehouse
    )
    assert (scoped, year) == (FILTERED, None)


def test_a_question_naming_no_period_is_pinned_to_the_latest_year(warehouse):
    scoped, year = scope_sql_to_default_year(
        "gpr", FILTERED, question=UNTIMED, engine=warehouse
    )
    assert year == scenario.CURRENT_YEAR
    assert f'"Year" = {scenario.CURRENT_YEAR}' in scoped


def test_a_query_scoped_by_billing_date_is_left_alone(warehouse):
    """Any date column, not only the year one — the two can only contradict."""
    sql = FILTERED + " AND Billing_Date >= '2024-01-01'"
    scoped, year = scope_sql_to_default_year(
        "gpr", sql, question=UNTIMED, engine=warehouse
    )
    assert (scoped, year) == (sql, None)


def test_a_shape_it_cannot_rewrite_runs_unchanged(warehouse):
    """A decline is the old behaviour, not an error — the turn keeps its answer."""
    sql = 'SELECT c.Carrier_Group FROM "GPR" c JOIN "Peers" p ON 1 = 1'
    scoped, year = scope_sql_to_default_year(
        "gpr", sql, question=UNTIMED, engine=warehouse
    )
    assert (scoped, year) == (sql, None)


# --------------------------------------------------------------------------- #
# 4. The join — the rows the reader sees, on the year the prose claims
# --------------------------------------------------------------------------- #


def _rows(engine, sql):
    from sqlalchemy import text

    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql)).mappings()]


def test_the_table_and_the_insight_land_on_the_same_year(warehouse):
    """The reported bug, as one assertion.

    `pin_latest_year` is the helper the insight's own scope goes through. The
    query the reader's table is built from must agree with it — not merely be
    scoped to *some* year.
    """
    _, insight_year = pin_latest_year(
        "gpr", {}, user_query=UNTIMED, engine=warehouse
    )
    scoped, table_year = scope_sql_to_default_year(
        "gpr", FILTERED, question=UNTIMED, engine=warehouse
    )
    assert table_year == insight_year == scenario.CURRENT_YEAR

    one_year = _rows(warehouse, scoped)[0]["premium"]
    every_year = _rows(warehouse, FILTERED)[0]["premium"]
    # The point of the fix: these differ. If the warehouse held one year they
    # would agree by accident and this test would prove nothing.
    assert one_year < every_year


def test_the_grouped_table_keeps_its_breakdown(warehouse):
    """Narrowing the period must not cost the cut the reader asked for."""
    scoped, _ = scope_sql_to_default_year(
        "gpr", GROUPED, question=UNTIMED, engine=warehouse
    )
    rows = _rows(warehouse, scoped)
    assert len(rows) > 1
    assert {"Product_Line", "premium"} <= set(rows[0])


def test_the_survey_rail_uses_its_own_year_column(warehouse):
    sql = 'SELECT AVG(Score) AS score FROM "Carriers" WHERE Carrier = \'ZURICH GROUP\''
    scoped, year = scope_sql_to_default_year(
        "survey", sql, question="How do brokers rate Zurich?", engine=warehouse
    )
    assert year is not None
    assert f'"Survey_Year" = {year}' in scoped
    assert _rows(warehouse, scoped) is not None


# --------------------------------------------------------------------------- #
# 5. The seat — the solver's own tool, and what it records as evidence
# --------------------------------------------------------------------------- #


@pytest.fixture
def solver_warehouse(engine, monkeypatch):
    """Point BOTH lookups at the fixture: the primitives' and `execute_sql`'s."""
    from sqlalchemy.orm import sessionmaker

    from core.initialization import Initialization

    monkeypatch.setattr(Initialization, "engine", engine)
    monkeypatch.setattr(Initialization, "Session", sessionmaker(bind=engine))
    return engine


def _run_sql_tool(evidence, question):
    from core.agents.analyst.common import build_tools

    tools = build_tools(evidence, question, lens="premium", flow="gpr")
    return next(t for t in tools if t.name == "run_sql")


def test_the_solvers_own_query_is_recorded_for_one_year(solver_warehouse):
    """The path the reader's table actually comes from, end to end.

    `run_sql` is what appends the rows the evidence panel renders. Before the
    guard it recorded whatever the model wrote, so a period-less question was
    answered in prose for the latest year and tabled across every year at once.
    """
    evidence = []
    _run_sql_tool(evidence, UNTIMED).invoke({"flow": "gpr", "sql": FILTERED})

    assert len(evidence) == 1
    recorded = evidence[0]
    assert f'"Year" = {scenario.CURRENT_YEAR}' in recorded["sql"]
    assert recorded["defaulted_year"] == scenario.CURRENT_YEAR


def test_the_answer_can_state_the_period_it_chose(solver_warehouse):
    """A default the reader cannot see is worse than no default.

    `defaulted_period` is what the answer's scope line reads; it was blank for a
    hand-written query because nothing stamped the year on that evidence.
    """
    from core.answers.scope import defaulted_period

    evidence = []
    _run_sql_tool(evidence, UNTIMED).invoke({"flow": "gpr", "sql": FILTERED})
    assert defaulted_period(evidence) == str(scenario.CURRENT_YEAR)


def test_a_question_that_named_its_year_is_recorded_as_no_default(solver_warehouse):
    evidence = []
    _run_sql_tool(evidence, TIMED).invoke({"flow": "gpr", "sql": FILTERED})

    assert evidence[0]["sql"] == FILTERED
    assert evidence[0]["defaulted_year"] is None


def test_the_latest_year_is_read_once_per_slice(solver_warehouse, monkeypatch):
    """A solver writes several queries a turn; the latest year cannot move."""
    from core.analytics import sql_period

    calls = []
    real = sql_period.latest_year_in

    def counted(flow, condition, **kwargs):
        calls.append((flow, condition))
        return real(flow, condition, **kwargs)

    # Patched where the seat READS it — `common` imported the name at module load.
    monkeypatch.setattr("core.agents.analyst.common.latest_year_in", counted)

    evidence = []
    tool = _run_sql_tool(evidence, UNTIMED)
    for _ in range(3):
        tool.invoke({"flow": "gpr", "sql": FILTERED})

    assert len(evidence) == 3
    assert len(calls) == 1 and calls[0][0] == "gpr"


# --------------------------------------------------------------------------- #
# 6. The period is read over the SLICE, not the book
# --------------------------------------------------------------------------- #


STILL_WRITING = "STILL WRITING"
LEFT_THE_MARKET = "LEFT THE MARKET"


@pytest.fixture
def uneven_book():
    """A warehouse where one carrier stopped a year before the others.

    The realistic shape the table-wide reading gets wrong: the book runs to 2025,
    but this carrier's last year is 2024. Pinning the book's latest year onto its
    query returns nothing at all — and "no data" for a carrier that has data is a
    worse answer than the all-years total this guard exists to remove.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE "GPR" (Carrier_Group TEXT, Year INTEGER, Premium REAL)'
        ))
        insert = text('INSERT INTO "GPR" VALUES (:carrier, :year, :premium)')
        rows = [
            {"carrier": STILL_WRITING, "year": 2024, "premium": 10.0},
            {"carrier": STILL_WRITING, "year": 2025, "premium": 20.0},
            {"carrier": LEFT_THE_MARKET, "year": 2024, "premium": 5.0},
        ]
        for row in rows:
            conn.execute(insert, row)
    return engine


def test_the_year_is_read_within_the_querys_own_scope(uneven_book):
    assert latest_year_in("gpr", "", engine=uneven_book) == 2025
    assert latest_year_in(
        "gpr", f"Carrier_Group = '{LEFT_THE_MARKET}'", engine=uneven_book
    ) == 2024


def test_a_carrier_that_stopped_early_keeps_its_rows(uneven_book):
    """The regression this guard could otherwise have introduced."""
    sql = (
        'SELECT SUM(Premium) AS premium FROM "GPR" '
        f"WHERE Carrier_Group = '{LEFT_THE_MARKET}'"
    )
    scoped, year = scope_sql_to_default_year(
        "gpr", sql, question=UNTIMED, engine=uneven_book
    )
    assert year == 2024
    assert _rows(uneven_book, scoped)[0]["premium"] == 5.0


def test_a_carrier_still_writing_gets_the_latest_year(uneven_book):
    sql = (
        'SELECT SUM(Premium) AS premium FROM "GPR" '
        f"WHERE Carrier_Group = '{STILL_WRITING}'"
    )
    scoped, year = scope_sql_to_default_year(
        "gpr", sql, question=UNTIMED, engine=uneven_book
    )
    assert year == 2025
    assert _rows(uneven_book, scoped)[0]["premium"] == 20.0
