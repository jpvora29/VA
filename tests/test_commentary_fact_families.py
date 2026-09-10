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


def _trend(**over):
    base = {"quarter_current": 50_000_000, "quarter_prior": 60_000_000,
            "quarter_label": "2025-Q4", "quarter_prior_label": "2024-Q4"}
    base.update(over)
    return {"subject": "Zurich", "trend": base}


@pytest.mark.parametrize("annual,quarter", [(27,5.1),(5,18),(12,10),(None,5),(27,None)])
def test_different_growth_bases_never_imply_momentum(annual, quarter):
    assert facts_trend._pace(annual, quarter) == ""


def test_quarter_observation_names_both_absolute_values_and_comparable_periods():
    line, = facts_trend.lines_for("challenges", _trend())
    assert all(value in line for value in ("$50M", "$60M", "2025-Q4", "2024-Q4"))
    assert "pace" not in line


def test_quarter_observation_needs_both_absolute_values():
    assert facts_trend.lines_for("challenges", _trend(quarter_prior=None)) == ()


def test_quarter_declines_and_gains_go_to_the_correct_section():
    assert facts_trend.lines_for("challenges", _trend())
    assert not facts_trend.lines_for("working", _trend())
    assert facts_trend.lines_for("working", _trend(quarter_current=70_000_000))
    assert not facts_trend.lines_for("challenges", _trend(quarter_current=70_000_000))


def test_thesis_can_report_either_direction_or_unchanged():
    for current in (50_000_000, 60_000_000, 70_000_000):
        assert facts_trend.lines_for("thesis", _trend(quarter_current=current))


def test_reporting_year_excludes_later_data(monkeypatch):
    from types import SimpleNamespace
    labels = [f"{y}-{m:02d}" for y in (2024, 2025) for m in range(1,13)]
    monkeypatch.setattr(facts_trend.C, "period_series", lambda *a, **k:
                        {"labels": labels, "values": [100] * len(labels)})
    result = SimpleNamespace(flow="gpr", engine=None)
    assert facts_trend.load(result, {"Year": 2023}) == {}
    assert facts_trend.load(result, {"Year": 2025})["quarter_label"] == "2025-Q4"


def test_a_failing_monthly_source_produces_no_trend(monkeypatch):
    from types import SimpleNamespace
    def explode(*a, **k):
        raise RuntimeError("no period column")
    monkeypatch.setattr(facts_trend.C, "period_series", explode)
    assert facts_trend.load(SimpleNamespace(flow="gpr", engine=None), {"Year": 2025}) == {}


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


def test_column_questions_and_eligible_findings_are_section_specific(deck_facts):
    from studio.template_fill import commentary_findings as F
    from studio.template_fill.commentary_evidence import build_pack
    pack = build_pack(deck_facts)
    assert F.brief(pack, "growth") != F.brief(pack, "challenges")
    assert F.brief(pack, "threats") != F.brief(pack, "working")
    assert all("growth" in f.topics for f in F.for_topic(pack, "growth"))


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
