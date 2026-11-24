"""The chart rule table: which chart a result set gets, decided in code.

Run:  pytest tests/test_chart_rules.py -q
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.answers.chart_rules import (
    MAX_SLICES,
    RULES,
    choose_chart,
    mix_chart_type,
    profile_rows,
)
from ui.chart_functions import (
    BENCHMARK_COLOR,
    CURRENT_COLOR,
    DOWN_COLOR,
    UP_COLOR,
    generate_chart,
    highlight_colors,
    latest_change_text,
)

RANKING = [
    {"Carrier": "ZURICH", "Premium": 9.0},
    {"Carrier": "GENERALI", "Premium": 7.0},
    {"Carrier": "AXA", "Premium": 5.0},
    {"Carrier": "ALLIANZ", "Premium": 8.0},
]
TREND = [
    {"Year": y, "Premium": v}
    for y, v in [(2022, 10), (2023, 12), (2024, 11), (2025, 14)]
]
BRIDGE = [
    {"Product_Line": "Property", "Change vs prior year": 5.0},
    {"Product_Line": "Casualty", "Change vs prior year": -3.0},
    {"Product_Line": "Marine", "Change vs prior year": 2.0},
]
PEERS = [
    {"Product": "Property", "Generali premium": 5.0, "Peer average": 7.0},
    {"Product": "Casualty", "Generali premium": 3.0, "Peer average": 2.0},
    {"Product": "Marine", "Generali premium": 4.0, "Peer average": 4.0},
]


def _mix(parts: int) -> list[dict]:
    share = 100 / parts
    return [{"Product": f"Line {i}", "Share %": share} for i in range(parts)]


def _draw(rows, choice):
    figure, message = generate_chart(pd.DataFrame(rows), choice.as_chart_data())
    assert figure is not None, message
    return figure


# ── the table ──────────────────────────────────────────────────────────────


def test_the_rules_are_tried_in_the_agreed_order():
    assert [r.name for r in RULES] == [
        "too_few",
        "bridge",
        "quarterly",
        "trend",
        "mix",
        "versus_peers",
        "ranking",
    ]


def test_one_value_is_a_kpi_not_a_chart():
    choice = choose_chart([{"Premium": 10.0}])
    assert choice.rule == "kpi" and not choice.has_chart
    assert choice.as_chart_data() == {}


def test_fewer_than_three_points_draw_no_chart():
    choice = choose_chart(RANKING[:2])
    assert choice.rule == "too_few" and not choice.has_chart


def test_a_change_split_by_item_is_a_waterfall():
    choice = choose_chart(BRIDGE)
    assert (choice.rule, choice.chart_type) == ("bridge", "waterfall")
    assert choice.y == ("Change vs prior year",)


def test_a_year_in_a_measure_name_is_not_a_time_axis():
    """ "Change vs prior year" names a year and holds amounts."""
    assert profile_rows(BRIDGE).time_axis == ""


def test_three_or_more_periods_are_a_line():
    choice = choose_chart(TREND)
    assert (choice.rule, choice.chart_type, choice.x) == ("trend", "line", "Year")
    assert "latest change is labelled" in choice.reason


def test_quarters_across_two_years_are_grouped_bars_not_a_line():
    """Quarter against quarter is a comparison of periods, not a path."""
    rows = [{"Quarter": f"Q{i}", "2024": 10 + i, "2025": 11 + i} for i in range(1, 5)]
    choice = choose_chart(rows)
    assert (choice.rule, choice.chart_type) == ("quarterly", "bar")
    assert choice.y == ("2024", "2025")
    assert choice.title == "2024 vs 2025 by quarter"


def test_a_single_years_quarters_are_bars_too():
    rows = [{"Quarter": f"Q{i}", "Premium": 10.0 + i} for i in range(1, 5)]
    assert choose_chart(rows).chart_type == "bar"


def test_the_grouped_quarter_bars_are_labelled():
    rows = [{"Quarter": f"Q{i}", "2024": 10.0 + i, "2025": 11.0 + i} for i in range(1, 5)]
    figure = _draw(rows, choose_chart(rows))
    assert all(trace.text is not None and len(trace.text) == 4 for trace in figure.data)


def test_a_trend_by_carrier_draws_one_line_per_carrier():
    rows = [
        {"Year": y, "Carrier": c, "Premium": float(y - 2000 + i)}
        for y in (2023, 2024, 2025)
        for i, c in enumerate("AB")
    ]
    choice = choose_chart(rows)
    assert choice.series == ("Carrier",) and choice.y == ("Premium",)


@pytest.mark.parametrize("parts", [2, 3, MAX_SLICES])
def test_a_few_parts_of_a_whole_are_a_donut(parts):
    rows = _mix(parts) if parts >= 3 else _mix(3)
    assert choose_chart(rows).chart_type == "donut"


def test_more_than_four_parts_are_sorted_bars_never_a_pie():
    choice = choose_chart(_mix(6))
    assert (choice.rule, choice.chart_type, choice.orientation) == ("mix", "bar", "h")
    assert mix_chart_type(MAX_SLICES + 1) == "bar"


def test_client_against_peers_is_a_dot_chart():
    choice = choose_chart(PEERS)
    assert (choice.rule, choice.chart_type) == ("versus_peers", "dot")
    assert choice.y == ("Generali premium", "Peer average")


def test_a_ranking_is_sorted_horizontal_bars_with_the_subject_highlighted():
    choice = choose_chart(RANKING, subjects=("Generali",))
    assert (choice.rule, choice.chart_type, choice.orientation) == (
        "ranking",
        "bar",
        "h",
    )
    assert choice.highlight == "GENERALI"
    assert "GENERALI is highlighted" in choice.reason


def test_rows_that_would_need_summing_are_not_charted():
    rows = [{"Carrier": "A", "Premium": 1.0}] * 4
    assert not choose_chart(rows).has_chart


def test_a_title_comes_from_the_columns_not_the_question():
    assert choose_chart(RANKING).title == "Premium by carrier"


def test_every_chart_says_why_it_is_that_chart():
    for rows in (RANKING, TREND, BRIDGE, PEERS, _mix(6)):
        data = choose_chart(rows).as_chart_data()
        assert data["reason"] and data["planned"] is True


# ── the drawing rules, through the real renderer ───────────────────────────


def test_the_ranking_renders_sideways_sorted_and_highlighted():
    figure = _draw(RANKING, choose_chart(RANKING, subjects=("GENERALI",)))
    bar = figure.data[0]
    assert bar.orientation == "h"
    assert list(bar.x) == sorted(bar.x)  # ascending up the axis = largest on top
    colours = dict(zip(bar.y, bar.marker.color))
    assert colours["GENERALI"] == CURRENT_COLOR
    assert {c for name, c in colours.items() if name != "GENERALI"} == {BENCHMARK_COLOR}
    assert all(bar.text)  # values labelled on the bars


def test_a_single_series_has_no_legend():
    figure = _draw(RANKING, choose_chart(RANKING))
    assert figure.layout.showlegend is not True


def test_the_line_labels_its_latest_change():
    figure = _draw(TREND, choose_chart(TREND))
    texts = [a.text for a in figure.layout.annotations]
    assert any("+27.3% vs 2024" in t for t in texts)


def test_the_latest_change_text_is_signed_and_skips_a_zero_base():
    assert latest_change_text(["Q1", "Q2"], [100, 90]) == "-10.0% vs Q1"
    assert latest_change_text(["Q1", "Q2"], [0, 90]) == ""
    assert latest_change_text(["Q1"], [5]) == ""


def test_the_waterfall_is_green_up_red_down():
    figure = _draw(BRIDGE, choose_chart(BRIDGE))
    trace = figure.data[0]
    assert trace.increasing.marker.color == UP_COLOR
    assert trace.decreasing.marker.color == DOWN_COLOR


def test_the_dot_chart_puts_the_client_in_the_accent_colour():
    figure = _draw(PEERS, choose_chart(PEERS))
    client, peers = [t for t in figure.data if t.mode == "markers"]
    assert "generali" in client.name.lower() and client.marker.color == CURRENT_COLOR
    assert "peer" in peers.name.lower() and peers.marker.color == BENCHMARK_COLOR


def test_a_highlight_absent_from_the_rows_colours_nothing():
    assert highlight_colors(["A", "B"], "C") is None
    assert highlight_colors(["A", "B"], "") is None


# ── which charts an answer carries: from the question ─────────────────────

from core.answers.chart_plan import _DEFAULT_ORDER, UNASKED_CHARTS, chart_keys_for  # noqa: E402


def test_a_question_naming_a_reading_leads_with_that_chart():
    assert chart_keys_for(_DEFAULT_ORDER, "Why did premium fall?")[0][0] == "contribution"
    assert chart_keys_for(_DEFAULT_ORDER, "Show quarter on quarter premium")[0][0] == "quarterly"
    assert chart_keys_for(_DEFAULT_ORDER, "Share of wallet headroom")[0][0] == "wallet"
    assert chart_keys_for(_DEFAULT_ORDER, "Portfolio mix by product")[0][0] == "mix"


def test_an_unspecific_question_gets_two_charts_not_the_catalogue():
    _keys, wanted = chart_keys_for(_DEFAULT_ORDER, "How is Zurich doing in Canada?")
    assert wanted == UNASKED_CHARTS


def test_different_questions_get_different_charts():
    def lead(q):
        keys, wanted = chart_keys_for(_DEFAULT_ORDER, q)
        return keys[:wanted]

    assert lead("Why did premium fall?") != lead("What is the position of chubb")
