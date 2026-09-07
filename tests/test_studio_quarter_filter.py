"""The Quarter filter — a QBR reports on a quarter, so Setup can pin one.

The GPR book has no quarter column; it records the month a premium was billed in. So the
filter is DERIVED (:data:`studio.compute.QUARTER_MONTHS`), and these tests hold the two
things that makes fragile:

* it must resolve to the right months everywhere the deck reads filters, not just where
  somebody remembered to expand it;
* it must stay OUT of the filter cube. The cube is the distinct combinations of the filter
  columns, and adding a twelve-value month column to it multiplies its width to answer a
  cascade nobody wants — a quarter has no business removing carriers from the carrier list.

Deterministic: the seed DB, no LLM.
"""
from __future__ import annotations

import pytest

from studio.compute import (
    QUARTER_COLUMN,
    QUARTER_MONTHS,
    _resolve_filters,
    quarter_months,
    quarter_options,
)


# ── the control ─────────────────────────────────────────────────────────────


def test_the_form_asks_for_a_quarter_next_to_the_year():
    """The period questions belong together — Year then Quarter, in reading order."""
    from studio.page.layout import GPR_FILTERS

    ids = [f["id"] for f in GPR_FILTERS]
    assert ids[:5] == ["region", "country", "carrier", "year", "quarter"]
    quarter = next(f for f in GPR_FILTERS if f["id"] == "quarter")
    assert quarter["multi"] is True                  # a QBR may span two quarters
    assert quarter["ph"] == "Full year"              # …and none pinned means the year


def test_the_choices_are_the_calendars_four_quarters():
    """A fixed vocabulary, not a distinct scan: Q3 missing from the list would read as
    "this carrier has no Q3" when it means "this filter combination has none"."""
    assert [o["value"] for o in quarter_options()] == ["Q1", "Q2", "Q3", "Q4"]


# ── what a quarter resolves to ──────────────────────────────────────────────


def test_a_quarter_is_its_three_months():
    assert quarter_months("Q1") == ("January", "February", "March")
    assert quarter_months(["Q4"]) == ("October", "November", "December")
    assert set(QUARTER_MONTHS) == {"Q1", "Q2", "Q3", "Q4"}
    assert sum(len(m) for m in QUARTER_MONTHS.values()) == 12


def test_several_quarters_resolve_in_calendar_order():
    """Q3 picked before Q1 is still January-first: the months are a set of rows, and an
    ``IN`` list that reads out of order is one more thing to explain in review."""
    assert quarter_months(["Q3", "Q1"]) == (
        "January", "February", "March", "July", "August", "September")


def test_the_resolver_turns_a_quarter_into_a_month_constraint():
    resolved = _resolve_filters({"carrier": "Zurich", "year": ["2025"], "quarter": ["Q3"]})

    assert resolved[QUARTER_COLUMN] == ("July", "August", "September")
    assert resolved["Year"] == (2025,)
    assert "quarter" not in resolved                 # never passed through as a column


@pytest.mark.parametrize("value", [None, "", [], ["all"], "All"])
def test_no_quarter_pinned_means_the_whole_year(value):
    assert _resolve_filters({"quarter": value}) == {}


def test_an_unknown_quarter_narrows_to_what_it_can_rather_than_failing():
    """A selection stored by an older form must not be able to fail a build."""
    assert quarter_months(["Q9"]) == ()
    assert _resolve_filters({"quarter": ["Q9"]}) == {}
    assert _resolve_filters({"quarter": ["Q9", "Q2"]})[QUARTER_COLUMN] == (
        "April", "May", "June")


# ── the perf guarantee ──────────────────────────────────────────────────────


def test_the_quarter_stays_out_of_the_filter_cube():
    """The cascade's cost is the cube's width. The month column would multiply it by
    twelve, and a quarter should not narrow the carrier or product lists anyway."""
    from studio.compute import FILTER_COLUMN
    from studio.data import cube_columns

    assert "quarter" not in FILTER_COLUMN
    assert QUARTER_COLUMN not in cube_columns("gpr")


def test_every_path_that_offers_the_filters_offers_the_quarter():
    """It is out of the cascade, so a caller could forget it — and a dropdown with no
    options cannot be used. The standalone demo rail did exactly that until
    :func:`studio.compute.form_options` gave the mapping one home."""
    from studio.authoring.generate import _friendly_options
    from studio.authoring.setup import cascade_filter_options
    from studio.compute import form_options

    assert _friendly_options(None)["quarter"] == quarter_options()
    assert cascade_filter_options({"carrier": "Zurich"}, None)["quarter"] == quarter_options()
    assert form_options({})["quarter"] == quarter_options()


def test_the_form_options_mapping_answers_for_every_filter_on_the_form():
    """One entry per dropdown the form draws, so a re-render never blanks one."""
    from studio.page.layout import GPR_FILTERS
    from studio.compute import form_options

    assert set(form_options({})) == {f["id"] for f in GPR_FILTERS}


# ── end to end over the book ────────────────────────────────────────────────


_SCOPE = {"carrier": "Zurich", "country": ["Singapore"], "year": [2025]}


def _total(**extra) -> float:
    """The premium the book holds under this selection — the figure Setup previews."""
    from studio.data import get_engine
    from studio.scope import scope_figures

    return scope_figures(_resolve_filters({**_SCOPE, **extra}),
                         flow="gpr", engine=get_engine()).total


def test_a_quarter_scoped_run_reports_the_quarters_premium():
    """The whole point: the deck's figures are the quarter's, not the year's."""
    from studio.compute import compute_overall

    assert 0 < _total(quarter=["Q3"]) < _total()
    result = compute_overall(filters={**_SCOPE, "quarter": ["Q3"]})
    assert result.resolved_filters[QUARTER_COLUMN] == ("July", "August", "September")


def test_the_four_quarters_add_up_to_the_year():
    """The mapping covers the calendar exactly — no month counted twice, none missed."""
    quarters = sum(_total(quarter=[q]) for q in ("Q1", "Q2", "Q3", "Q4"))
    assert quarters == pytest.approx(_total(), rel=1e-6)


def test_the_scope_preview_names_the_period_it_is_showing():
    """A tile reading "2025" over a Q3 total describes a year the deck does not report."""
    from studio.authoring.setup import period_label

    assert period_label({"year": [2025], "quarter": ["Q3"]}) == "2025 · Q3"
    assert period_label({"year": [2024, 2025]}) == "2024, 2025"
    assert period_label({}) == "All"
