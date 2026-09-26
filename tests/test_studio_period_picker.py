"""Setup's timeline: YTD / R12M naming, the month picker, and where it sits on the form.

The picker is a thin skin over the period layer (:mod:`studio.period`): every answer it
gives is a pair of ISO dates that the existing date-range / R12M paths already read, so
the tests below check the mapping, the transitions, and the one new label ("YTD Aug 2026").
"""
from __future__ import annotations

import json
from datetime import date

from dash import no_update

from studio import period as P
from studio.authoring.period_picker import next_state, paint
from studio.authoring.setup import period_selection
from studio.authoring.setup_summary import bar_state
from studio.page.authoring import period_picker as PP
from studio.page.authoring.setup import PERIOD_BASIS_OPTIONS, setup_body

LATEST = {"latest": [2026, 8], "first_year": 2023}


def _rendered(component) -> str:
    return json.dumps(component, default=lambda o: getattr(o, "__dict__", str(o)))


# ── naming ───────────────────────────────────────────────────────────────────


def test_setup_names_the_bases_ytd_and_r12m_without_changing_their_values():
    assert [o["label"] for o in PERIOD_BASIS_OPTIONS] == ["YTD", "R12M"]
    assert [o["value"] for o in PERIOD_BASIS_OPTIONS] == [P.BASIS_CALENDAR, P.BASIS_R12M]


def test_the_line_under_the_control_is_short():
    latest = (2026, 8)
    assert PP.summary_line(PP.read_answer({}), PP.BASIS_YTD, latest) == "YTD 2026 vs 2025"
    feb = PP.read_answer(PP.ending_dates((2026, 2), PP.BASIS_YTD))
    assert PP.summary_line(feb, PP.BASIS_YTD, latest) == "YTD Feb 2026 vs YTD Feb 2025"
    span = PP.read_answer(PP.range_dates((2026, 4), (2026, 7)))
    assert PP.summary_line(span, PP.BASIS_YTD, latest) == "Apr – Jul 2026 vs Apr – Jul 2025"


def test_the_period_sentence_says_ytd_and_r12m():
    assert P.describe(P.PeriodChoice(), latest=(2026, 8)) == "YTD 2026 against 2025."
    assert P.describe(P.PeriodChoice(P.BASIS_R12M), latest=(2026, 8)).startswith("R12M Aug 2026")


# ── the answer each pick writes ──────────────────────────────────────────────


def test_an_ending_month_on_ytd_is_january_to_that_month():
    assert PP.ending_dates((2026, 8), PP.BASIS_YTD) == {
        "from": "2026-01-01", "to": "2026-08-31", "custom": False}


def test_an_ending_month_on_r12m_only_sets_the_end():
    assert PP.ending_dates((2026, 2), PP.BASIS_R12M) == {
        "from": None, "to": "2026-02-28", "custom": False}


def test_a_range_is_ordered_whichever_month_was_clicked_first():
    assert PP.range_dates((2026, 6), (2026, 3)) == {
        "from": "2026-03-01", "to": "2026-06-30", "custom": True}


def test_switching_basis_keeps_the_ending_month():
    ytd = PP.ending_dates((2026, 8), PP.BASIS_YTD)
    assert PP.rebase(ytd, PP.BASIS_R12M) == PP.ending_dates((2026, 8), PP.BASIS_R12M)
    assert PP.rebase({}, PP.BASIS_R12M) == {"from": None, "to": None, "custom": False}


def test_r12m_collapses_a_custom_range_to_where_it_ends():
    """R12M is twelve months by definition — it would silently ignore the first month."""
    custom = PP.range_dates((2026, 3), (2026, 6))
    assert PP.rebase(custom, PP.BASIS_YTD) == custom
    assert PP.rebase(custom, PP.BASIS_R12M) == PP.ending_dates((2026, 6), PP.BASIS_R12M)


def test_presets_read_the_latest_month_in_the_data():
    assert PP.preset_month(PP.PRESET_LAST_QUARTER, (2026, 8)) == (2026, 6)
    assert PP.preset_month(PP.PRESET_LAST_QUARTER, (2026, 9)) == (2026, 9)
    assert PP.preset_month(PP.PRESET_LAST_QUARTER, (2026, 2)) == (2025, 12)
    assert PP.preset_month(PP.PRESET_LAST_YEAR, (2026, 8)) == (2025, 12)
    assert PP.preset_month(PP.PRESET_LATEST, (2026, 8)) is None


# ── the picker's transitions ─────────────────────────────────────────────────


def test_a_month_click_sets_the_end_of_the_period():
    dates, view, basis = next_state({"type": "qs6-month", "m": 5}, dates={}, view={"year": 2026},
                                    basis=PP.BASIS_YTD, meta=LATEST)
    assert dates == {"from": "2026-01-01", "to": "2026-05-31", "custom": False}
    assert basis is no_update


def test_a_range_takes_two_clicks_and_moves_r12m_to_ytd():
    view = {"year": 2026, "mode": PP.MODE_RANGE}
    dates, view, basis = next_state({"type": "qs6-month", "m": 3}, dates={}, view=view,
                                    basis=PP.BASIS_R12M, meta=LATEST)
    assert dates is no_update and view["anchor"] == [2026, 3]
    dates, view, basis = next_state({"type": "qs6-month", "m": 7}, dates={}, view=view,
                                    basis=PP.BASIS_R12M, meta=LATEST)
    assert dates == {"from": "2026-03-01", "to": "2026-07-31", "custom": True}
    assert basis == PP.BASIS_YTD and view["anchor"] is None


def test_the_year_cannot_step_past_the_data():
    assert next_state("qs6-year-next", dates={}, view={"year": 2026}, basis=PP.BASIS_YTD,
                      meta=LATEST) == (no_update, no_update, no_update)
    _, view, _ = next_state("qs6-year-prev", dates={}, view={"year": 2026},
                            basis=PP.BASIS_YTD, meta=LATEST)
    assert view["year"] == 2025


def test_months_after_the_latest_billing_cannot_be_picked():
    classes, disabled, year, *_ = paint({}, {"year": 2026}, PP.BASIS_YTD, LATEST)
    assert year == "2026"
    assert disabled == [False] * 8 + [True] * 4
    assert "is-latest" in classes[7]


def test_a_custom_range_is_painted_start_to_end():
    dates = PP.range_dates((2026, 2), (2026, 5))
    classes, *_ = paint(dates, {"year": 2026}, PP.BASIS_YTD, LATEST)
    assert "is-start" in classes[1] and "in-range" in classes[2] and "is-end" in classes[4]


def test_the_trigger_says_what_was_chosen():
    latest = (2026, 8)
    assert PP.trigger_label(PP.read_answer({}), PP.BASIS_YTD, latest) == "Aug 2026 (latest)"
    assert PP.trigger_kicker(PP.read_answer({})) == "Ends"
    assert PP.trigger_kicker(PP.read_answer(PP.range_dates((2026, 1), (2026, 3)))) == "Range"
    assert PP.trigger_label(PP.read_answer(PP.ending_dates((2026, 6), "calendar")),
                            PP.BASIS_YTD, latest) == "Jun 2026"
    assert PP.trigger_label(PP.read_answer(PP.range_dates((2025, 11), (2026, 2))),
                            PP.BASIS_YTD, latest) == "Nov 2025 – Feb 2026"


# ── the picker's answer reaches the period layer unchanged ───────────────────


def test_a_ytd_ending_month_becomes_a_ytd_window_on_the_slides():
    dates = PP.ending_dates((2026, 8), PP.BASIS_YTD)
    choice = P.period_choice(period_selection(PP.BASIS_YTD, *PP.date_keys(dates)))
    window = P.window_for(choice, latest=(2026, 8))
    assert window.kind == P.KIND_RANGE and window.is_ytd
    assert window.label() == "YTD Aug 2026" and window.label(2025) == "YTD Aug 2025"
    assert window.start == date(2026, 1, 1) and window.end == date(2026, 8, 31)


def test_an_r12m_ending_month_is_the_twelve_months_to_it():
    dates = PP.ending_dates((2026, 3), PP.BASIS_R12M)
    choice = P.period_choice(period_selection(PP.BASIS_R12M, *PP.date_keys(dates)))
    window = P.window_for(choice, latest=(2026, 8))
    assert (window.kind, window.start, window.end) == (P.KIND_R12M, date(2025, 4, 1),
                                                       date(2026, 3, 31))


def test_latest_month_leaves_the_selection_exactly_as_before():
    """No dates, YTD: byte-identical to a selection saved before the picker existed."""
    assert period_selection(PP.BASIS_YTD, *PP.date_keys({})) == {}


# ── where the timeline sits, and the action bar ──────────────────────────────


def test_the_timeline_is_part_of_the_market_and_period_pane():
    form = _rendered(setup_body([], filter_options={}, filter_values={}))
    pane = form.index("Market & period")
    assert pane < form.index("studio-period-basis") < form.index("Benchmark")
    assert "studio-date-range" not in form                 # the from -> to picker is gone
    assert '"qs6-month"' in form and "studio-period-dates" in form


def test_every_filter_sits_together_before_the_timeline():
    form = _rendered(setup_body([], filter_options={}, filter_values={}))
    assert "More filters" not in form
    timeline = form.index("studio-period-basis")
    for col in ("carrier", "country", "year", "quarter", "product_line", "region",
                "business_line", "cover_line", "industry", "sub_industry", "client_segment"):
        assert form.index(f'"col": "{col}"') < timeline, col


def test_the_action_bar_says_whether_the_brief_is_ready():
    assert bar_state(None, 16, "premium", "carrier_leadership", "governed")[1] == \
        "Pick a carrier to begin"
    icon, text, summary, ready = bar_state("Zurich", 16, "premium", "carrier_leadership",
                                           "governed")
    assert ready and text == "Scope selected — Zurich"
    assert summary == "16 pages · GPR only · Carrier team"
    assert not bar_state("Zurich", 0, "premium", "marsh_regional", "governed")[3]
