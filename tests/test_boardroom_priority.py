"""The watchlist priority rules.

The roadmap's hard requirement is that a `High` can name the threshold it
crossed. These tests pin the two halves of that promise: the LABEL follows the
approved thresholds (never a model's opinion), and the EXPLANATION that ships
with it lists the tests that produced the label.

Run:  pytest tests/test_boardroom_priority.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.boardroom import priority
from core.boardroom.priority import Thresholds, WatchSignals

APPROVED = Thresholds(
    approved=True,
    currency="GBP",
    material_premium=5_000_000.0,
    material_share_of_wallet_pct=5.0,
    watch_move_pct=5.0,
    severe_move_pct=10.0,
    persistent_periods=2,
)


def label(**kwargs) -> str:
    return priority.classify(WatchSignals(**kwargs), APPROVED).label


# ── the labels ───────────────────────────────────────────────────────────────


def test_material_premium_plus_a_breach_is_high():
    assert label(premium_exposed=12_400_000, movement_pct=-14.2) == "High"


def test_material_premium_with_two_adverse_signals_is_high():
    """Below the breach threshold, but persistent AND a governed KPI crossed."""
    assert (
        label(
            premium_exposed=8_000_000,
            movement_pct=-6.0,
            consecutive_periods=3,
            breached_kpi="Rank fell from #10 to #14",
        )
        == "High"
    )


def test_one_material_adverse_signal_is_medium():
    assert label(premium_exposed=8_000_000, movement_pct=-6.0, consecutive_periods=2) == "Medium"


def test_a_repeated_early_warning_is_medium_even_below_materiality():
    assert label(premium_exposed=100_000, movement_pct=-6.0, consecutive_periods=2) == "Medium"


def test_a_small_single_movement_is_low():
    assert label(premium_exposed=100_000, movement_pct=-3.0) == "Low"


def test_share_of_wallet_can_carry_materiality_without_a_premium_figure():
    assert label(share_of_wallet_pct=19.5, movement_pct=-14.2) == "High"


def test_a_favourable_movement_never_counts_as_adverse():
    """`adverse=False` means the measure moved the carrier's way."""
    assert label(premium_exposed=12_400_000, movement_pct=14.2, adverse=False) == "Low"


def test_incomplete_periods_leave_the_item_unrated():
    """No comparable periods, no defensible label — the facts stand alone."""
    verdict = priority.classify(
        WatchSignals(premium_exposed=12_400_000, movement_pct=-14.2, periods_comparable=False),
        APPROVED,
    )
    assert verdict.label == "Unrated"
    assert "not comparable" in verdict.reason


# ── the explanation ──────────────────────────────────────────────────────────


def test_every_verdict_lists_the_tests_behind_it():
    verdict = priority.classify(WatchSignals(premium_exposed=12_400_000, movement_pct=-14.2), APPROVED)
    names = [t.name for t in verdict.tests]
    assert names == [
        "Materiality",
        "Magnitude",
        "Early warning",
        "Persistence",
        "Business breach",
        "Data confidence",
    ]
    assert all(t.detail for t in verdict.tests), "a rule test with no detail cannot be defended"


def test_the_reason_quotes_the_threshold_that_was_crossed():
    verdict = priority.classify(WatchSignals(premium_exposed=12_400_000, movement_pct=-14.2), APPROVED)
    assert "10%" in verdict.reason
    assert "14.2%" in verdict.reason


def test_the_verdict_carries_whether_the_thresholds_are_approved():
    unapproved = priority.classify(
        WatchSignals(premium_exposed=12_400_000, movement_pct=-14.2),
        Thresholds(**{**APPROVED.__dict__, "approved": False}),
    )
    assert unapproved.approved is False
    assert priority.classify(WatchSignals(premium_exposed=1.0), APPROVED).approved is True


def test_the_dict_form_carries_everything_the_card_shows():
    payload = priority.classify(WatchSignals(premium_exposed=12_400_000, movement_pct=-14.2), APPROVED).as_dict()
    assert set(payload) == {
        "priority",
        "priority_reason",
        "priority_tests",
        "priority_approved",
        "priority_thresholds",
    }
    assert payload["priority_thresholds"], "the drawer needs the numbers in force"


# ── ranking ──────────────────────────────────────────────────────────────────


def test_items_rank_by_premium_exposed_first():
    """Sort order is the roadmap's: exposure, then magnitude, then persistence."""
    rated = priority.rate_items(
        [
            {"risk": "small but severe", "premium_exposed_value": 100_000, "movement_pct": -40.0},
            {"risk": "large", "premium_exposed_value": 20_000_000, "movement_pct": -11.0},
            {"risk": "medium", "premium_exposed_value": 6_000_000, "movement_pct": -12.0},
        ]
    )
    assert [item["risk"] for item in rated] == ["large", "medium", "small but severe"]
    assert all(item["priority"] for item in rated)


def test_rating_is_pure_and_never_mutates_the_input():
    items = [{"risk": "x", "premium_exposed_value": 1.0}]
    priority.rate_items(items)
    assert items == [{"risk": "x", "premium_exposed_value": 1.0}]


def test_missing_facts_do_not_raise():
    rated = priority.rate_items([{"risk": "no numbers at all"}])
    assert rated[0]["priority"] in {"High", "Medium", "Low", "Unrated"}


# ── the configured thresholds ────────────────────────────────────────────────


def test_shipped_thresholds_parse():
    t = priority.get_thresholds()
    assert t.material_premium > 0
    assert t.severe_move_pct >= t.watch_move_pct
    assert t.persistent_periods >= 2
    assert t.summary()


@pytest.mark.parametrize(
    "value,expected",
    [(12_400_000, "£12.4m"), (900_000, "£900.0k"), (2_400_000_000, "£2.4bn"), (None, "—")],
)
def test_money_formatting_matches_the_card(value, expected):
    assert priority.format_money(value, "GBP") == expected
