"""Commentary QA rules — report, never rewrite.

The rules are matters of judgement rather than faithfulness, so the contract these pin is
as much about what QA must NOT do (delete a sentence, empty a cell) as what it catches.
"""
from __future__ import annotations

import pytest

from studio.template_fill import commentary_qa as QA


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")


def _cells(**cells) -> dict:
    """A fill payload keyed the way the prose providers key theirs."""
    return {f"fbnote:0:1:1:{i}": text for i, text in enumerate(cells.values())}


# ── terminology precision ────────────────────────────────────────────────────


def test_market_rank_is_flagged_because_the_denominator_is_the_marsh_book():
    issues = QA.check(_cells(a="Market rank improved 3 places to #3 of 12 this year."))
    assert [i.code for i in issues] == ["market_overstated"]


def test_rank_within_the_marsh_book_is_not_flagged():
    assert not QA.check(_cells(
        a="Rank within the Marsh book improved 3 places to #3 of 12 this year."))


def test_addressable_without_appetite_or_capacity_is_flagged():
    issues = QA.check(_cells(
        a="Renewable Energy is a $184.9M addressable market the account does not write."))
    assert [i.code for i in issues] == ["unevidenced_addressable"]


def test_addressable_with_validation_evidence_passes():
    assert not QA.check(_cells(
        a="Renewable Energy is addressable once appetite and capacity are confirmed here."))


# ── unbenchmarked language ───────────────────────────────────────────────────


def test_an_adjective_with_nothing_to_measure_it_against_is_flagged():
    issues = QA.check(_cells(a="The book showed strong momentum across the year in Cyber."))
    assert [i.code for i in issues] == ["unbenchmarked_adjective"]


def test_the_same_adjective_against_a_benchmark_passes():
    assert not QA.check(_cells(
        a="Growth was strong against a Marsh book that grew 9.9% over the same year."))


# ── length ───────────────────────────────────────────────────────────────────


def test_a_cell_past_three_sentences_is_flagged():
    long = " ".join(f"This is commentary sentence number {n} on a slide." for n in range(5))
    assert "cell_runs_long" in {i.code for i in QA.check(_cells(a=long))}


# ── repetition, across cells ─────────────────────────────────────────────────


def test_the_same_claim_in_two_cells_is_reported_with_both_places():
    claim = "Zurich grew its book with Marsh 28.6% year on year to $208M overall."
    issues = QA.check(_cells(a=claim, b=claim))
    repeated = [i for i in issues if i.code == "repeated_claim"]
    assert len(repeated) == 1 and len(repeated[0].where) == 2


def test_repetition_ignores_casing_and_the_full_stop():
    issues = QA.check(_cells(a="Premium grew 57.1% to $44M in the year.",
                             b="premium grew 57.1% to $44M in the year"))
    assert any(i.code == "repeated_claim" for i in issues)


def test_a_short_label_is_not_a_claim():
    """KPI callouts and column headings repeat by design and are not repetition."""
    assert not QA.check(_cells(a="Carrier GWP", b="Carrier GWP"))


# ── what QA must not do ──────────────────────────────────────────────────────


def test_check_never_alters_the_values_it_is_given():
    values = _cells(a="Market rank improved 3 places to #3 of 12 this year.")
    before = dict(values)
    QA.check(values)
    assert values == before, "QA rewrote the deck's prose"


def test_kpi_and_non_prose_roles_are_left_alone():
    """Only the prose roles are judged; a ``fb:`` KPI callout is not commentary."""
    assert not QA.check({"fb:0:1:1:4": "$414M (+13.2%)", "template_year": 2025,
                         "gwp_bars": {"a": 1}})
