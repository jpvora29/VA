"""How far the data reaches, and comparing like with like when it stops mid-year.

The bug these exist to prevent: a warehouse loaded through Q2 2025 holds half a year.
Compared against a complete 2024 that reads as a ~50% collapse, and the deck says the
book fell off a cliff when nothing changed at all.

The dataset below is built so the arithmetic is checkable by eye — 2024 has four equal
quarters, 2025 has the first two at the same run-rate. Whole-year YoY must say -50%;
like-for-like must say 0%.

Run:  pytest tests/analytics/test_period_reach.py -q
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from core.analytics import (
    PrimitiveArgs,
    compute_yoy,
    compute_yoy_to_date,
    get_latest_quarter,
    get_latest_year,
)
from core.analytics.frames import frame_source

_COLUMNS = ["Carrier_Group", "Country", "Product_Line", "Year", "Billing_Date", "Premium"]


def _rows(spec):
    """(carrier, country, product, year, date, premium) tuples from a compact spec."""
    return [("Zurich", "Canada", product, year, f"{year}-{month}-15", premium)
            for product, year, month, premium in spec]


# 2024: Cyber 100 in each of the four quarters (400); Property 50 each (200).
# 2025: Cyber 100 in Q1 and Q2 only (200);            Property 50 each (100).
# Same run-rate, half the year.
_PARTIAL = _rows(
    [("Cyber", 2024, m, 100.0) for m in ("01", "04", "07", "10")]
    + [("Property", 2024, m, 50.0) for m in ("01", "04", "07", "10")]
    + [("Cyber", 2025, m, 100.0) for m in ("02", "05")]
    + [("Property", 2025, m, 50.0) for m in ("02", "05")]
)

# The same book, but 2025 runs the full four quarters.
_COMPLETE = _rows(
    [("Cyber", year, m, 100.0) for year in (2024, 2025) for m in ("01", "04", "07", "10")]
)


def _engine(rows):
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text(
            'CREATE TABLE GPR (Carrier_Group TEXT, Country TEXT, Product_Line TEXT, '
            'Year INTEGER, Billing_Date TEXT, Premium REAL)'
        ))
        if rows:  # executemany rejects an empty parameter list
            conn.execute(
                text('INSERT INTO GPR VALUES (:cg, :co, :pl, :yr, :bd, :pr)'),
                [dict(zip(("cg", "co", "pl", "yr", "bd", "pr"), row)) for row in rows],
            )
    return eng


def _frames(rows):
    """The same rows as an uploaded dataset, for the pandas executor."""
    return frame_source({"GPR": pd.DataFrame(rows, columns=_COLUMNS)})


@pytest.fixture
def partial():
    return _engine(_PARTIAL)


@pytest.fixture
def complete():
    return _engine(_COMPLETE)


def _args(**kwargs):
    base = dict(flow="gpr", metric="premium", group_by=(), filters={})
    return PrimitiveArgs(**{**base, **kwargs})


# Both executors, one contract: every behavioural test runs on the SQL engine and on
# the pandas twin, so an uploaded book cannot quietly disagree with the warehouse.
@pytest.fixture(params=["sql", "pandas"])
def source(request):
    return (lambda rows: _engine(rows)) if request.param == "sql" else _frames


# ── how far does the data reach ──────────────────────────────────────────────


def test_latest_year_is_the_last_year_with_data(source):
    fact = get_latest_year(_args(), engine=source(_PARTIAL))[0]
    assert fact.rendered == "2025"
    assert fact.dims["year"] == 2025


def test_latest_quarter_reports_the_quarter_and_flags_the_year_incomplete(source):
    fact = get_latest_quarter(_args(), engine=source(_PARTIAL))[0]
    assert fact.rendered == "Q2 2025"
    assert fact.dims["quarter"] == 2
    assert fact.dims["period"] == "2025-Q2"
    assert fact.dims["complete"] is False
    assert fact.dims["periods_present"] == 2


def test_a_year_running_to_q4_is_reported_complete(source):
    fact = get_latest_quarter(_args(), engine=source(_COMPLETE))[0]
    assert fact.dims["complete"] is True
    assert fact.rendered == "Q4 2025"


def test_month_grain_reports_the_last_month_loaded(partial):
    fact = get_latest_quarter(_args(), grain="month", engine=partial)[0]
    assert fact.rendered == "M05 2025"
    assert fact.dims["month"] == 5
    assert fact.dims["complete"] is False


# ── the scope rule: period filters must not answer the question for us ───────


def test_the_turns_year_filter_is_ignored_when_asking_how_far_data_goes(source):
    """A turn pinned to 2024 must still be told the data reaches 2025 — otherwise the
    primitive just repeats the year it was handed, and nothing can detect a stale load."""
    fact = get_latest_year(_args(filters={"Year": 2024}), engine=source(_PARTIAL))[0]
    assert fact.dims["year"] == 2025


def test_a_non_period_filter_is_still_honoured(source):
    """Dropping the year must not drop the country — the latest period genuinely can
    differ per market, so the rest of the scope has to survive."""
    assert get_latest_year(_args(filters={"Country": "Nowhere"}),
                           engine=source(_PARTIAL)) == []


# ── the point: like-for-like growth ──────────────────────────────────────────


def test_whole_year_yoy_reads_a_partial_year_as_a_collapse(partial):
    """Not a bug in compute_yoy — this is what it means, and why the aligned tool
    exists. 200 against 400 really is -50%; it just isn't the answer to the question."""
    facts = compute_yoy(_args(), engine=partial)
    assert [(f.dims["year"], f.rendered) for f in facts] == [(2025, "-50.0%")]


def test_like_for_like_yoy_compares_the_same_quarters_of_each_year(source):
    """Q1-Q2 2025 (300) against Q1-Q2 2024 (300) — flat, which is the truth."""
    facts = compute_yoy_to_date(_args(), engine=source(_PARTIAL))
    assert [(f.dims["year"], f.rendered) for f in facts] == [(2025, "+0.0%")]
    assert facts[0].dims["through"] == "Q2"
    assert "truncated to Q2" in facts[0].formula


def test_on_a_complete_year_the_aligned_answer_matches_plain_yoy(source):
    """So a caller can prefer compute_yoy_to_date unconditionally."""
    engine = source(_COMPLETE)
    aligned = compute_yoy_to_date(_args(), engine=engine)
    assert [f.rendered for f in aligned] == ["+0.0%"]
    assert aligned[0].dims["through"] == "Q4"


def test_alignment_holds_per_cut(source):
    """Cyber grew 20% in the half-year it has; Property was flat. The whole-year view
    would have called both a collapse."""
    rows = _rows(
        [("Cyber", 2024, m, 100.0) for m in ("01", "04", "07", "10")]
        + [("Property", 2024, m, 50.0) for m in ("01", "04", "07", "10")]
        + [("Cyber", 2025, m, 120.0) for m in ("02", "05")]
        + [("Property", 2025, m, 50.0) for m in ("02", "05")]
    )
    facts = compute_yoy_to_date(_args(group_by=("Product_Line",)), engine=source(rows))
    assert {f.dims["Product_Line"]: f.rendered for f in facts} == {
        "Cyber": "+20.0%", "Property": "+0.0%"
    }


def test_the_comparison_survives_a_turn_pinned_to_one_year(source):
    """compute_yoy has nothing to compare when the scope pins a single year; the
    aligned tool drops period filters for exactly that reason."""
    engine = source(_PARTIAL)
    assert compute_yoy(_args(filters={"Year": 2025}), engine=engine) == []
    aligned = compute_yoy_to_date(_args(filters={"Year": 2025}), engine=engine)
    assert [f.rendered for f in aligned] == ["+0.0%"]


def test_month_grain_aligns_on_the_month(partial):
    """Through May: 2025 has Feb+May (300), 2024 has Jan+Apr (300)."""
    facts = compute_yoy_to_date(_args(), grain="month", engine=partial)
    assert facts[0].dims["through"] == "M05"
    assert facts[0].rendered == "+0.0%"


# ── graceful degradation ─────────────────────────────────────────────────────


def test_a_year_only_flow_yields_no_quarter_rather_than_raising(partial):
    """The survey carries Survey_Year and no date column, so there is no quarter to
    report. That must be an empty answer, never an exception mid-turn."""
    survey = _args(flow="survey", metric="score")
    assert get_latest_quarter(survey, engine=partial) == []
    assert compute_yoy_to_date(survey, engine=partial) == []


def test_an_empty_book_yields_no_facts(source):
    assert get_latest_year(_args(), engine=source([])) == []
    assert get_latest_quarter(_args(), engine=source([])) == []
    assert compute_yoy_to_date(_args(), engine=source([])) == []


def test_an_unknown_grain_is_rejected(partial):
    with pytest.raises(ValueError, match="grain"):
        get_latest_quarter(_args(), grain="fortnight", engine=partial)


# ── the tools the model sees ─────────────────────────────────────────────────


def test_the_new_tools_are_offered_to_the_model():
    from core.analytics.tools import tool_names

    gpr = tool_names("gpr")
    assert {"get_latest_year", "get_latest_quarter", "compute_yoy_to_date"} <= set(gpr)
    # The survey has no date column, so the quarter-shaped tools are not offered.
    survey = tool_names("survey")
    assert "get_latest_year" in survey
    assert "get_latest_quarter" not in survey
    assert "compute_yoy_to_date" not in survey


def test_a_period_tool_does_not_ask_the_model_for_a_metric():
    """"What is the latest quarter?" is a calendar question; offering `metric` would
    only invite a meaningless argument."""
    from core.analytics.tools import tool_schemas

    schemas = {s["function"]["name"]: s["function"]["parameters"]["properties"]
               for s in tool_schemas("gpr")}
    assert "metric" not in schemas["get_latest_quarter"]
    assert "grain" in schemas["get_latest_quarter"]
    assert "metric" in schemas["compute_yoy_to_date"]


def test_the_aligned_column_names_the_span_it_covers(partial):
    """A reader must never see a bare "YoY" that secretly covers half a year."""
    from core.analytics.tools import column_label

    fact = compute_yoy_to_date(_args(), engine=partial)[0]
    assert column_label(fact) == "YoY_%_through_Q2"
