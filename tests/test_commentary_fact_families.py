"""The two fact families that are not another reading of the headline.

Every family `feedback._facts` loaded described the scope as a level or a year-on-year
delta, so every column argued from the same six numbers and — however differently briefed
— converged on the same sentences. These two answer different questions:

    facts_mix    how the premium is DISTRIBUTED across the lines it is written in
    facts_trend  where the book is HEADING, the only time axis in the evidence

Each owns its family end to end: how the fact is loaded, and how it is said. Deterministic
throughout — these run against the seed DB with no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pytest

from studio.template_fill import facts_mix, facts_trend


# ── how the book is distributed ──────────────────────────────────────────────


def test_the_mix_is_read_on_the_axis_the_scope_has_not_already_pinned():
    """A product sub-deck already knows it is Cyber; its mix question is about markets."""
    assert facts_mix.mix_dimension({"Carrier_Group": "Zurich"}) == "Product_Line"
    assert facts_mix.mix_dimension({"Product_Line": "Cyber"}) == "Country"
    assert facts_mix.mix_dimension({"Country": "Japan"}) == "Product_Line"


def test_a_scope_pinned_to_one_cell_has_no_mix_to_report():
    """One product in one market is a single cell — a one-row distribution says nothing."""
    assert facts_mix.mix_dimension({"Product_Line": "Cyber", "Country": "Japan"}) is None


def test_a_multi_select_pin_is_not_a_pin():
    """Two products in scope still spread across lines, so the line axis still reads."""
    assert facts_mix.mix_dimension({"Product_Line": ["Cyber", "Marine"]}) == "Product_Line"


def _mix(**over) -> Dict[str, Any]:
    base = {"dim": "Product_Line", "label": "lines of business", "lead": "Financial Lines",
            "lead_share": 22.1, "top3": 62.0, "n": 6, "concentrated": True}
    base.update(over)
    return {"mix": base}


def test_a_concentrated_book_states_its_shape_and_stops():
    """The glossary's `concentration` entry: state the shape, let the reader conclude."""
    line, = facts_mix.lines_for("thesis", _mix())
    assert "Financial Lines" in line and "22.1%" in line and "62%" in line
    for banned in ("risky", "fragile", "exposed", "vulnerable"):
        assert banned not in line.lower()


def test_a_spread_book_is_not_described_as_concentrated():
    line, = facts_mix.lines_for("thesis", _mix(concentrated=False, top3=41.0))
    assert "no single one dominant" in line


def test_the_mix_only_reaches_the_columns_it_answers():
    """Bucketed per column: a shared pool is drained by whichever column fills first."""
    assert facts_mix.lines_for("thesis", _mix())
    assert facts_mix.lines_for("growth", _mix())
    assert facts_mix.lines_for("challenges", _mix()) == ()


def test_a_missing_mix_costs_its_own_line_and_nothing_else():
    assert facts_mix.lines_for("thesis", {}) == ()
    assert facts_mix.lines_for("thesis", {"mix": {}}) == ()


# ── where the book is heading ────────────────────────────────────────────────


def _trend(**over) -> Dict[str, Any]:
    base = {"ttm": 810_598_028.0, "ttm_pct": 27.0, "annual_pct": 26.4, "quarter_pct": 5.1,
            "quarter_label": "2025-Q4", "pace": "slowing"}
    base.update(over)
    return {"trend": base}


def test_a_quarter_far_below_the_years_pace_reads_as_slowing():
    assert facts_trend._pace(27.0, 5.1) == "slowing"


def test_a_quarter_ahead_of_the_years_pace_reads_as_accelerating():
    assert facts_trend._pace(5.0, 18.0) == "accelerating"


def test_a_quarter_in_line_with_the_year_is_not_called_a_turn():
    """Below the threshold the two readings agree, and "slowing" would be noise."""
    assert facts_trend._pace(12.0, 10.0) == "holding"


def test_the_pace_read_needs_both_figures():
    assert facts_trend._pace(None, 5.1) == ""
    assert facts_trend._pace(27.0, None) == ""


def test_the_momentum_line_always_prints_both_figures_it_rests_on():
    """The glossary's `momentum` entry: the two numbers are the claim, the word is the
    reading. A sentence may only print a figure the evidence carries."""
    line, = facts_trend.lines_for("challenges", _trend())
    assert "26.4%" in line and "5.1%" in line and "2025-Q4" in line
    assert "not still running" in line


def test_the_momentum_line_prints_the_year_it_judged_on_not_the_trailing_window():
    """Regression: the pace was judged on the year's movement and the sentence printed the
    trailing-twelve figure — a different window and a different number, so a true sentence
    was evidencing a claim it had not actually measured."""
    line, = facts_trend.lines_for("challenges", _trend(annual_pct=26.4, ttm_pct=0.4))
    assert "26.4%" in line
    assert "0.4%" not in line


def test_a_pace_reading_with_no_annual_figure_says_nothing():
    """It is a COMPARISON; without both sides there is no claim to make."""
    assert facts_trend.lines_for("challenges", _trend(annual_pct=None)) == ()


def test_a_slowing_book_is_a_challenge_and_an_accelerating_one_is_working():
    assert facts_trend.lines_for("challenges", _trend(pace="slowing"))
    assert facts_trend.lines_for("working", _trend(pace="slowing")) == ()
    assert facts_trend.lines_for("working", _trend(pace="accelerating"))
    assert facts_trend.lines_for("challenges", _trend(pace="accelerating")) == ()


def test_the_thesis_takes_the_reading_whichever_way_it_goes():
    for pace in ("slowing", "accelerating", "holding"):
        assert facts_trend.lines_for("thesis", _trend(pace=pace)), pace


def test_a_trend_that_ran_past_the_reported_year_is_dropped(monkeypatch):
    """The primitives return the latest period IN THE DATA, which is not this page's
    period when the deck reports a closed prior year — a figure dated wrong is worse
    than no figure."""
    monkeypatch.setattr(facts_trend.C, "ttm",
                        lambda *a, **k: {"current": 1.0, "ttm_pct": 9.0})
    monkeypatch.setattr(facts_trend.C, "qoq",
                        lambda *a, **k: {"latest": 4.0, "latest_label": "2025-Q4"})

    @dataclass
    class R:
        flow: str = "gpr"
        engine: Any = None

    assert facts_trend.load(R(), {"Year": 2023}) == {}
    assert facts_trend.load(R(), {"Year": 2025})["quarter_label"] == "2025-Q4"


def test_a_failing_primitive_costs_its_own_family(monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("no period column")

    monkeypatch.setattr(facts_trend.C, "ttm", explode)

    @dataclass
    class R:
        flow: str = "gpr"
        engine: Any = None

    assert facts_trend.load(R(), {"Year": 2025}) == {}


# ── both families reach the evidence pack, and the columns that own them ─────


@pytest.fixture(scope="module")
def deck_facts():
    from studio.compute import compute_overall
    from studio.authoring.config import BREAKDOWNS, engine
    from studio.template_fill import feedback

    result = compute_overall(filters={"carrier": "Zurich"}, breakdowns=BREAKDOWNS,
                             engine=engine, style="balanced")
    return feedback._facts(result, feedback._reporting_filters(result))


def test_the_pack_now_carries_a_time_axis(deck_facts):
    from studio.template_fill import commentary_evidence as E

    ids = {e.fact_id for e in E.build_pack(deck_facts).items}
    assert "trend.ttm" in ids and "mix.concentration" in ids


def test_every_column_leads_from_a_different_slice_of_one_pack(deck_facts):
    """The other half of why five briefed columns read as one paragraph: they were handed
    an IDENTICAL pack and each reached for the headline, the easiest fact to write about."""
    from studio.template_fill import commentary as CM
    from studio.template_fill import commentary_evidence as E

    pack = E.build_pack(deck_facts)
    openings = {}
    for topic in ("thesis", "performance", "challenges", "growth", "priorities"):
        lead = pack.as_brief(CM.evidence_focus(topic)).split("ALSO TRUE")[0]
        openings[topic] = lead.strip().splitlines()[1]
    assert len(set(openings.values())) == len(openings), openings


def test_the_whole_pack_is_still_offered_to_every_column(deck_facts):
    """Split, never filtered: the draft a column is shown cites what ITS composer chose,
    and `check_numbers` drops a sentence whose figure is not in the pack."""
    from studio.template_fill import commentary as CM
    from studio.template_fill import commentary_evidence as E

    pack = E.build_pack(deck_facts)
    brief = pack.as_brief(CM.evidence_focus("growth"))
    for item in pack.items:
        assert f"[{item.fact_id}]" in brief


def test_the_new_families_enlarge_the_deterministic_pool_too(deck_facts):
    """The ledger thins a page whose claims are already spoken for; a bigger pool is the
    fix. This must hold with no model at all — a fallback run gets it as well."""
    from studio.template_fill import feedback

    with_families = feedback.points("thesis", deck_facts)
    original = feedback._FACT_FAMILIES
    feedback._FACT_FAMILIES = ()
    try:
        without = feedback.points("thesis", deck_facts)
    finally:
        feedback._FACT_FAMILIES = original
    assert len(with_families) > len(without)
