"""Two results that are different findings must not look the same.

The report on the drivers panel: it "always just gives a chart", so the fourth
visit looks exactly like the first and people stop opening it. A decline carried
by two countries and a decline spread across eleven product lines are different
findings, and the panel now says which it is before drawing anything
(:mod:`core.answers.shape`), then draws the picture that fits.

The second half is the question a ranking by size can never answer. The biggest
part of the book tops the waterfall every quarter, which is true and is not news;
:mod:`core.answers.unusual` reads each slice against ITS OWN history and finds
the one that is small but has just turned.

The flow covered is the real one:

    rows behind an answer -> decompose -> classify -> unusual -> the panel

Run:  pytest tests/test_driver_shapes.py -q -o pythonpath=.
"""
from __future__ import annotations

from dash.development.base_component import Component

from core.answers import shape as shape_mod
from core.answers import unusual as unusual_mod
from core.answers.contribution import decompose
from core.answers.drivers import analyse, is_supported, leaders_of
from ui.components.contribution import contribution_panel


def rows(periods, column, dimension, series):
    """Rows in the shape a result set arrives in: one row per period per slice."""
    return [
        {column: period, dimension: name, "Premium": values[i] * 1_000_000}
        for i, period in enumerate(periods)
        for name, values in series.items()
    ]


YEARS = ["2023", "2024"]

# One slice is nearly the whole movement.
SINGLE = rows(YEARS, "Year", "Product_Line",
              {"Property": [11.3, 8.2], "Cyber": [1.4, 1.8], "Marine": [2.4, 2.4]})

# Big movement both ways that nearly cancels: the net is the misleading number.
OFFSETTING = rows(YEARS, "Year", "Product_Line",
                  {"Property": [11.3, 8.2], "Cyber": [1.4, 4.3], "Marine": [2.4, 2.5]})

# Two of five carry it.
CONCENTRATED = rows(YEARS, "Year", "Country",
                    {"UK": [10, 7], "France": [8, 6], "Spain": [5, 4.8],
                     "Italy": [4, 3.9], "Poland": [3, 2.95]})

# Everything drifted the same way; nothing leads.
BROAD = rows(YEARS, "Year", "Product_Line",
             {"Property": [10, 9.1], "Casualty": [9, 8.2], "Cyber": [8, 7.3],
              "Marine": [7, 6.4], "Aviation": [6, 5.5], "Energy": [5, 5.05],
              "Construction": [4.5, 4.1]})

QUARTERS = ["2024 Q1", "2024 Q2", "2024 Q3", "2024 Q4", "2025 Q1", "2025 Q2"]

# UK is the big mover and has fallen all along; Germany is small and has just
# turned after five quarters of growth. Germany is the finding.
HISTORY = rows(QUARTERS, "Quarter", "Country", {
    "UK": [20, 19, 18, 17, 16, 13],
    "Germany": [4, 4.3, 4.6, 4.9, 5.2, 4.9],
    "France": [8, 8.1, 8, 8.1, 8, 8.1],
    "Spain": [5, 5.1, 5.2, 5.1, 5.2, 5.3],
})


def walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)


def text_of(node) -> str:
    return " ".join(
        n.children for n in walk(node) if isinstance(getattr(n, "children", None), str)
    )


def classes(node) -> list:
    return [(getattr(n, "className", "") or "") for n in walk(node)]


# ── the classification ──────────────────────────────────────────────────────


def test_each_kind_of_result_is_recognised_as_its_own_shape():
    got = {
        "single": shape_mod.classify(decompose(SINGLE)).shape,
        "offsetting": shape_mod.classify(decompose(OFFSETTING)).shape,
        "concentrated": shape_mod.classify(decompose(CONCENTRATED)).shape,
        "broad": shape_mod.classify(decompose(BROAD)).shape,
    }
    assert got == {
        "single": shape_mod.SINGLE,
        "offsetting": shape_mod.OFFSETTING,
        "concentrated": shape_mod.CONCENTRATED,
        "broad": shape_mod.BROAD,
    }


def test_nothing_moving_is_its_own_shape_not_a_finding():
    still = rows(YEARS, "Year", "Product_Line", {"Property": [8.0, 8.0], "Cyber": [1.0, 1.0]})
    assert shape_mod.classify(decompose(still)).shape == shape_mod.FLAT


def test_offsetting_is_checked_before_single():
    """One big fall against one big rise is not "the fall" — it is the pair."""
    profile = shape_mod.classify(decompose(OFFSETTING))
    assert profile.shape == shape_mod.OFFSETTING
    assert profile.lost < 0 and profile.gained > 0


def test_the_lead_names_the_slices_it_is_about():
    profile = shape_mod.classify(decompose(CONCENTRATED))
    assert profile.leaders == ("UK", "France")
    assert "UK" in profile.lead and "France" in profile.lead


def test_the_lead_sentence_and_the_share_it_quotes_are_the_same_number():
    """Rounding twice put "93%" in the sentence above a bar labelled "94%"."""
    profile = shape_mod.classify(decompose(CONCENTRATED))
    assert f"{profile.covered_pct:.0f}%" in profile.lead


def test_an_offsetting_lead_says_the_net_is_not_the_story():
    lead = shape_mod.classify(decompose(OFFSETTING)).lead
    assert "cancelled out" in lead
    assert "barely moved" in lead


def test_a_broad_lead_counts_the_slices_rather_than_naming_one():
    lead = shape_mod.classify(decompose(BROAD)).lead
    assert "6 of 7 product lines" in lead


# ── what is unusual, as opposed to what is large ────────────────────────────


def test_a_small_slice_that_has_just_turned_is_found():
    contribution = decompose(HISTORY)
    profile = shape_mod.classify(contribution)
    found = unusual_mod.find_unusual(HISTORY, contribution, already_told=profile.leaders)
    germany = next(u for u in found if u.name == "Germany")
    assert germany.kind == unusual_mod.REVERSAL
    assert germany.reason == "its first fall in 5 quarters"


def test_the_slice_the_lead_already_named_sorts_below_the_one_it_did_not():
    """"Small, but it has just turned" is the finding the ranking hides."""
    contribution = decompose(HISTORY)
    profile = shape_mod.classify(contribution)
    found = unusual_mod.find_unusual(HISTORY, contribution, already_told=profile.leaders)
    assert [u.name for u in found] == ["Germany", "UK"]
    assert found[0].is_leader is False and found[1].is_leader is True


def test_two_periods_produce_no_history_reading_at_all():
    """Silence, not a hedge: two points have no character to be out of."""
    contribution = decompose(SINGLE)
    assert unusual_mod.find_unusual(SINGLE, contribution) == []


def test_a_slice_missing_from_a_period_is_dropped_rather_than_read_as_zero():
    """A hole read as zero manufactures a collapse and a recovery."""
    partial = [r for r in HISTORY if not (r["Country"] == "Spain" and r["Quarter"] == "2024 Q3")]
    series = unusual_mod.series_by_slice(
        partial, period="Quarter", dimension="Country", measure="Premium"
    )
    assert "Spain" not in series and "Germany" in series


def test_the_period_is_named_from_its_own_column():
    assert unusual_mod.period_word("Fiscal_Quarter") == "quarter"
    assert unusual_mod.period_word("Year") == "year"
    assert unusual_mod.period_word("Reporting_Bucket") == "period"


def test_one_earlier_move_is_not_a_pattern_to_be_out_of():
    """Three periods leave a single prior move to judge against.

    "Its biggest move ever" off one earlier move says only that two numbers
    differ, and "its first fall" off one earlier rise is noise. Both signals need
    two prior moves, so nothing fires here.
    """
    short = rows(["Q1", "Q2", "Q3"], "Quarter", "Country",
                 {"UK": [10, 11, 9], "France": [8, 8, 8]})
    assert unusual_mod.find_unusual(short, decompose(short)) == []


# ── the whole analysis ──────────────────────────────────────────────────────


def test_the_analysis_carries_the_shape_the_lead_and_the_unusual_together():
    payload = analyse(HISTORY)
    assert is_supported(payload)
    assert payload["shape"] == shape_mod.SINGLE
    assert payload["headline"] == payload["profile"]["lead"]
    assert [u["name"] for u in payload["unusual"]] == ["Germany", "UK"]
    assert leaders_of(payload) == ["UK"]


def test_rows_that_cannot_be_decomposed_still_return_their_reason():
    payload = analyse([{"Product_Line": "Property", "Premium": 1}])
    assert not is_supported(payload)
    assert "one period" in payload["note"]


def test_the_analysis_survives_the_trip_through_the_store():
    import json

    payload = json.loads(json.dumps(analyse(HISTORY)))
    assert payload["profile"]["leaders"] == ["UK"]


# ── the panel ───────────────────────────────────────────────────────────────


def test_each_shape_draws_its_own_lead():
    """The whole point: four results, four different pictures."""
    marks = {
        "conc": contribution_panel(analyse(CONCENTRATED)),
        "gains-losses": contribution_panel(analyse(OFFSETTING)),
        "spread": contribution_panel(analyse(BROAD)),
        "single": contribution_panel(analyse(SINGLE)),
    }
    for expected, panel in marks.items():
        found = [c for c in classes(panel) if c.startswith("contrib-lead")]
        assert found == [f"contrib-lead {expected}"], expected


def test_the_ranked_bars_stay_under_every_shape():
    """The lead changes; the evidence does not, or two answers stop comparing."""
    for data in (CONCENTRATED, OFFSETTING, BROAD, SINGLE):
        panel = contribution_panel(analyse(data))
        assert any(c.startswith("contrib-bar-fill") for c in classes(panel))


def test_an_offsetting_result_does_not_quote_a_share_of_a_near_zero_net():
    """It printed "+3100%" — correct, and a share of the number it just dismissed."""
    panel = contribution_panel(analyse(OFFSETTING))
    shown = text_of(panel)
    assert "Of movement" in shown and "Of total" not in shown
    assert "3100%" not in shown
    assert "not of the net" in shown


def test_every_other_shape_keeps_the_share_of_total_and_its_caveat():
    shown = text_of(contribution_panel(analyse(CONCENTRATED)))
    assert "Of total" in shown
    assert "can pass 100%" in shown


def test_a_slice_that_did_not_move_is_neither_a_rise_nor_a_fall():
    """$0 printed green read as growth, and a tiny negative rounded to "-0%"."""
    panel = contribution_panel(analyse(SINGLE))
    flat = [
        n for n in walk(panel)
        if (getattr(n, "className", "") or "") == "contrib-delta flat"
    ]
    assert flat and str(flat[0].children) == "$0"
    assert "-0%" not in text_of(panel)


def test_the_rows_the_lead_names_are_marked_in_the_evidence():
    panel = contribution_panel(analyse(CONCENTRATED))
    marked = [c for c in classes(panel) if c == "contrib-row is-lead"]
    assert len(marked) == 2


def test_the_panel_carries_its_shape_so_a_stylesheet_can_see_it():
    panel = contribution_panel(analyse(BROAD))
    assert "shape-broad" in (panel.className or "")


def test_the_unusual_section_appears_only_when_the_rows_carry_history():
    assert "changed unexpectedly" in text_of(contribution_panel(analyse(HISTORY)))
    assert "changed unexpectedly" not in text_of(contribution_panel(analyse(SINGLE)))


def test_the_unusual_section_says_what_it_measured_against():
    shown = text_of(contribution_panel(analyse(HISTORY)))
    assert "against its own history" in shown


def test_premium_is_printed_in_the_reporting_currency():
    """One config decides it, and the drivers panel reads the same one as the deck."""
    from core.boardroom.money import reporting_currency

    assert reporting_currency() == "USD"
    assert "$" in text_of(contribution_panel(analyse(SINGLE)))


def test_a_movement_carries_its_sign_outside_the_symbol():
    shown = text_of(contribution_panel(analyse(SINGLE)))
    assert "-$3.1m" in shown and "$-3.1m" not in shown
