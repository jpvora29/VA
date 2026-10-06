"""A commentary line that only restates figures the deck already gave is dropped.

The case is the Overall pages of a real Zurich/Singapore deck: the growth headline said on
the highlights page, again in Key Messages and again in the ranking page's Key Highlights;
the share of wallet in three fields; "defend Cyber … #1" twice in one field.
"""
from __future__ import annotations

from studio.template_fill.repeat_prune import Figure, figures_of, prune_repeats, role_order

OVERALL = {
    "note:2:34:0": "Zurich's Marsh-placed premium grew 28.6% to $208M, while total Marsh-placed "
                   "premium grew 9.9%.\nCarrier ranks #5 of 12 carriers, up 1 place.",
    "note:3:10:0": "At 9.1% share of wallet the carrier sits 1.7 percentage points below the "
                   "top-5 average of 10.8%.",
    "note:3:16:0": "Its share of Marsh placements in this scope is 9.1%.\n"
                   "Rank improved in 3 of 6 lines, furthest in Cyber, up 5 places to #1.",
    "note:3:20:0": "The first calls are to defend Cyber ($44M) and scale Financial Lines ($44M).\n"
                   "Cyber is the position to defend, since the carrier ranks #1 in the Marsh book.",
    "note:3:22:0": "Zurich wrote $207.9M with Marsh in 2025, up 28.6% year on year.\n"
                   "Zurich's share of Marsh placements rose to 9.1% from 7.8%.",
    "fbnote:5:3:0:0": "Cyber carried $22M of the $46M added (47%).\n"
                      "Zurich grew its Marsh-placed premium 28.6% year on year to $208M.",
}


def test_figures_are_read_at_slide_precision():
    assert Figure("money", "208") in figures_of("wrote $207.9M")
    assert Figure("money", "2100") in figures_of("placed $2.1B")
    assert Figure("pct", "28.6") in figures_of("up 28.6% on the year")
    assert Figure("pp", "1.7") in figures_of("1.7 percentage points below")
    assert Figure("rank", "1") in figures_of("ranks #1")
    assert figures_of("in 2025, across 6 lines") == ()      # years and counts are not findings


def test_the_overall_pages_say_each_figure_once():
    out = prune_repeats(OVERALL)
    assert out["note:2:34:0"] == OVERALL["note:2:34:0"]               # first saying stays
    assert out["note:3:16:0"].startswith("Rank improved")            # 9.1% said already
    assert "position to defend" not in out["note:3:20:0"]            # Cyber #1 said already
    assert out["note:3:22:0"] == "Zurich's share of Marsh placements rose to 9.1% from 7.8%."
    assert out["fbnote:5:3:0:0"] == "Cyber carried $22M of the $46M added (47%)."


def test_a_line_that_adds_one_new_figure_stays():
    """"rose to 9.1% from 7.8%" repeats the share but adds the movement."""
    out = prune_repeats({"note:1:1:0": "Share of wallet is 9.1%.",
                         "note:2:1:0": "Share rose to 9.1% from 7.8%."})
    assert out["note:2:1:0"] == "Share rose to 9.1% from 7.8%."


def test_a_rank_only_repeats_beside_the_same_name():
    out = prune_repeats({"note:1:1:0": "Cyber moved up to #1.",
                         "note:2:1:0": "Property also ranks #1 for the carrier."})
    assert out["note:2:1:0"] == "Property also ranks #1 for the carrier."


def test_a_field_is_never_emptied_and_unfigured_lines_stay():
    out = prune_repeats({"note:1:1:0": "Premium grew 28.6% to $208M.",
                         "note:2:1:0": "Premium grew 28.6% to $208M.",
                         "note:3:1:0": "Momentum is broad-based.\nPremium grew 28.6%."})
    assert out["note:2:1:0"] == "Premium grew 28.6% to $208M."     # whole field: first line kept
    assert out["note:3:1:0"] == "Momentum is broad-based."


def test_pages_are_read_in_slide_order_not_insertion_order():
    texts = {"note:5:1:0": "Premium grew 28.6%.", "note:2:9:0": "Premium grew 28.6% again.",
             "note:2:9:1": "Margin held."}
    out = prune_repeats(texts)
    assert out["note:2:9:0"] == "Premium grew 28.6% again."
    assert out["note:5:1:0"] == "Premium grew 28.6%."               # kept: its field's only line
    assert sorted(texts, key=role_order)[0] == "note:2:9:0"
