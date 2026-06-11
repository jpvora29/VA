"""Tests for the staged boardroom digest.

One core call + deterministic widget-signal detection + one small fill call per
detected widget — replacing the single giant generation that under-filled the
optional widget tail.

Run:  pytest tests/test_boardroom_staged.py -q -o pythonpath=.
"""
from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import HumanMessage

import core.agents.boardroom as boardroom
from core.schemas.boardroom import (
    BoardroomCore,
    ComparisonView,
    KpiCard,
    OpportunityMap,
    PositioningMatrix,
    PositioningPoint,
    TimelineEvent,
)

# ── deterministic widget-signal detection ────────────────────────────────────


def test_two_periods_fire_timeline():
    rows = [("premium", [{"Year": 2023, "Premium": 1.0}, {"Year": 2024, "Premium": 2.0}])]
    assert "timeline" in boardroom.detect_widget_signals(rows, "")


def test_single_period_does_not_fire_timeline():
    rows = [("premium", [{"Year": 2024, "Premium": 1.0}, {"Year": 2024, "Premium": 2.0}])]
    assert "timeline" not in boardroom.detect_widget_signals(rows, "")


def test_multi_country_fires_map_and_radar():
    rows = [("premium", [{"Country": "Canada", "P": 1}, {"Country": "France", "P": 2}])]
    signals = boardroom.detect_widget_signals(rows, "")
    assert {"opportunity_map", "opportunities"} <= signals


def test_multi_product_fires_map_and_radar():
    rows = [("premium", [{"Product_Line": "Cyber", "P": 1}, {"Product_Line": "Property", "P": 2}])]
    signals = boardroom.detect_widget_signals(rows, "")
    assert {"opportunity_map", "opportunities"} <= signals


def test_carriers_fire_comparison_and_battlecards():
    rows = [("premium", [{"Carrier_Group": "ZURICH GROUP", "P": 1}, {"Carrier_Group": "AXA", "P": 2}])]
    signals = boardroom.detect_widget_signals(rows, "")
    assert {"comparison", "battlecards"} <= signals


def test_peer_commentary_fires_comparison_without_carrier_rows():
    rows = [("premium", [{"Year": 2024, "P": 1}])]
    signals = boardroom.detect_widget_signals(rows, "Zurich trails the peer average.")
    assert "comparison" in signals
    assert "battlecards" not in signals  # no carrier values in rows


def test_premium_plus_perception_fires_positioning_across_sets():
    rows = [
        ("gpr:trend", [{"Carrier_Group": "ZURICH GROUP", "Premium": 5.0}]),
        ("survey:scores", [{"Carrier": "Zurich", "Score": 7.1}]),
    ]
    assert "positioning" in boardroom.detect_widget_signals(rows, "")


def test_scalar_lookup_fires_nothing():
    rows = [("premium", [{"Premium": 5.0}])]
    assert boardroom.detect_widget_signals(rows, "") == set()


# ── empty-widget collapsing ──────────────────────────────────────────────────


def test_nullify_empty_collapses_structurally_empty_widgets():
    assert boardroom._nullify_empty("comparison", ComparisonView()) is None
    assert boardroom._nullify_empty("opportunity_map", OpportunityMap()) is None
    assert boardroom._nullify_empty("positioning", PositioningMatrix()) is None
    kept = PositioningMatrix(points=[PositioningPoint(label="Zurich")])
    assert boardroom._nullify_empty("positioning", kept) is kept


# ── staged node assembly ─────────────────────────────────────────────────────


class _StubPredictor:
    def __init__(self, **fields) -> None:
        self._fields = fields
        self.calls = 0

    def __call__(self, **_kwargs) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(**self._fields)


def _state() -> dict:
    return {
        "boardroom_mode": True,
        "messages": [HumanMessage(content="Zurich premium trend", id="m1")],
        "current_route": "premium",
        "gpr_response": "Premium grew from $1M (2023) to $2M (2024).",
        "gpr_query_result": [
            {"Year": 2023, "Premium": 1.0},
            {"Year": 2024, "Premium": 2.0},
        ],
    }


def test_staged_node_assembles_core_plus_detected_widgets(monkeypatch):
    core = BoardroomCore(
        title="Zurich", headline="Premium doubled.", kpis=[KpiCard(label="Premium", value="$2M")]
    )
    core_stub = _StubPredictor(core=core)
    timeline_stub = _StubPredictor(
        timeline=[TimelineEvent(period="2024", title="Premium +100%")]
    )
    never_stub = _StubPredictor()
    monkeypatch.setattr(boardroom, "_CORE_PREDICTOR", core_stub)
    monkeypatch.setattr(
        boardroom,
        "_WIDGET_PREDICTORS",
        {
            "timeline": (timeline_stub, "timeline"),
            "opportunity_map": (never_stub, "opportunity_map"),
            "opportunities": (never_stub, "opportunities"),
            "positioning": (never_stub, "positioning"),
            "comparison": (never_stub, "comparison"),
            "battlecards": (never_stub, "battlecards"),
        },
    )

    digest = boardroom.boardroom_node(_state())["boardroom"]

    assert digest["title"] == "Zurich"
    assert digest["kpis"][0]["value"] == "$2M"
    # Only the supported widget got a call; the rest stayed untouched.
    assert timeline_stub.calls == 1
    assert never_stub.calls == 0
    assert digest["timeline"][0]["title"] == "Premium +100%"
    assert digest["comparison"] is None
    assert digest["positioning"] is None


def test_widget_failure_never_sinks_the_dashboard(monkeypatch):
    core_stub = _StubPredictor(core=BoardroomCore(title="Zurich"))

    class _Boom:
        def __call__(self, **_kwargs):
            raise RuntimeError("widget exploded")

    monkeypatch.setattr(boardroom, "_CORE_PREDICTOR", core_stub)
    monkeypatch.setattr(
        boardroom,
        "_WIDGET_PREDICTORS",
        {name: (_Boom(), field) for name, (_, field) in boardroom._WIDGET_PREDICTORS.items()},
    )

    digest = boardroom.boardroom_node(_state())["boardroom"]
    assert digest["title"] == "Zurich"
    assert digest["timeline"] == []


def test_core_failure_returns_none_and_off_mode_clears(monkeypatch):
    class _Boom:
        def __call__(self, **_kwargs):
            raise RuntimeError("core exploded")

    monkeypatch.setattr(boardroom, "_CORE_PREDICTOR", _Boom())
    assert boardroom.boardroom_node(_state()) == {"boardroom": None}
    assert boardroom.boardroom_node({"boardroom_mode": False}) == {"boardroom": None}
