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
    TimelineEvent,
)
from core.schemas.boardroom_explainable import (
    PortfolioBubble,
    ProductPortfolioMap,
    QuarterlyPerformance,
    TopCarriers,
    WatchItem,
    Watchlist,
)

# ── deterministic widget-signal detection ────────────────────────────────────


def test_two_periods_fire_timeline():
    rows = [("premium", [{"Year": 2023, "Premium": 1.0}, {"Year": 2024, "Premium": 2.0}])]
    assert "timeline" in boardroom.detect_widget_signals(rows, "")


def test_single_period_does_not_fire_timeline():
    rows = [("premium", [{"Year": 2024, "Premium": 1.0}, {"Year": 2024, "Premium": 2.0}])]
    assert "timeline" not in boardroom.detect_widget_signals(rows, "")


def test_multi_product_with_premium_fires_headroom():
    rows = [
        ("premium", [
            {"Product_Line": "Cyber", "Premium": 1},
            {"Product_Line": "Property", "Premium": 2},
        ])
    ]
    assert "headroom" in boardroom.detect_widget_signals(rows, "")


def test_products_without_a_premium_measure_fire_no_headroom():
    """Headroom is carrier premium against Marsh premium; with no premium column
    there is nothing explainable to show."""
    rows = [("survey", [{"Product_Line": "Cyber", "Score": 7}, {"Product_Line": "Property", "Score": 6}])]
    assert "headroom" not in boardroom.detect_widget_signals(rows, "")


def test_industry_dimension_fires_whitespace():
    rows = [
        (
            "premium",
            [
                {"SIC_Major_Class": "Manufacturing", "Premium": 3},
                {"SIC_Major_Class": "Construction", "Premium": 2},
            ],
        )
    ]
    assert "whitespace" in boardroom.detect_widget_signals(rows, "")


def test_one_industry_is_not_an_industry_view():
    """A column with a single value cannot be RANKED by industry.

    The whole result set being Manufacturing (because that is what was asked
    about) used to fire the widget anyway, and the board grew an Industry Focus
    page with nothing on it.
    """
    rows = [("premium", [{"SIC_Major_Class": "Manufacturing", "Premium": 3}])]
    assert "whitespace" not in boardroom.detect_widget_signals(rows, "")


def test_retired_score_widgets_are_never_requested():
    """The roadmap replaced the 0-100 widgets; a new digest must not ask for one."""
    rows = [
        ("premium", [
            {"Country": "Canada", "Product_Line": "Cyber", "Premium": 1, "Score": 7},
            {"Country": "France", "Product_Line": "Property", "Premium": 2, "Score": 6},
        ])
    ]
    signals = boardroom.detect_widget_signals(rows, "peers")
    # `positioning_actual` joined the retired list: share of wallet against a
    # broker score plotted two unrelated measures on one chart.
    assert not (
        {"opportunity_map", "opportunities", "positioning", "positioning_actual"} & signals
    )


def test_two_quarters_fire_quarterly_instead_of_the_timeline():
    rows = [("premium", [{"Quarter": "Q1 2026", "Premium": 1}, {"Quarter": "Q2 2026", "Premium": 2}])]
    signals = boardroom.detect_widget_signals(rows, "")
    assert "quarterly" in signals
    assert "timeline" not in signals


def test_two_periods_and_a_measure_fire_the_watchlist():
    rows = [("premium", [{"Year": 2023, "Premium": 1}, {"Year": 2024, "Premium": 2}])]
    assert "watchlist" in boardroom.detect_widget_signals(rows, "")


def test_carriers_fire_comparison_and_battlecards():
    rows = [("premium", [{"Carrier_Group": "ZURICH GROUP", "P": 1}, {"Carrier_Group": "AXA", "P": 2}])]
    signals = boardroom.detect_widget_signals(rows, "")
    assert {"comparison", "battlecards"} <= signals


def test_peer_commentary_fires_comparison_without_carrier_rows():
    rows = [("premium", [{"Year": 2024, "P": 1}])]
    signals = boardroom.detect_widget_signals(rows, "Zurich trails the peer average.")
    assert "comparison" in signals
    assert "battlecards" not in signals  # no carrier values in rows


def test_two_carriers_with_premium_fire_top_carriers():
    rows = [
        ("gpr:trend", [{"Carrier_Group": "ZURICH GROUP", "Premium": 5.0}]),
        ("gpr:peers", [{"Carrier_Group": "Peer 1", "Premium": 4.0}]),
    ]
    assert "top_carriers" in boardroom.detect_widget_signals(rows, "")


def test_products_with_premium_fire_both_product_views():
    """Headroom ranks the money left on the table; the map shows the book's shape."""
    rows = [
        ("premium", [
            {"Product_Line": "Property", "Premium": 8.0},
            {"Product_Line": "Cyber", "Premium": 1.0},
        ])
    ]
    signals = boardroom.detect_widget_signals(rows, "")
    assert {"headroom", "portfolio_map"} <= signals


def test_scalar_lookup_fires_nothing():
    rows = [("premium", [{"Premium": 5.0}])]
    assert boardroom.detect_widget_signals(rows, "") == set()


# ── empty-widget collapsing ──────────────────────────────────────────────────


def test_nullify_empty_collapses_structurally_empty_widgets():
    assert boardroom._nullify_empty("comparison", ComparisonView().model_dump()) is None
    assert boardroom._nullify_empty("portfolio_map", ProductPortfolioMap().model_dump()) is None
    assert boardroom._nullify_empty("top_carriers", TopCarriers().model_dump()) is None
    kept = ProductPortfolioMap(bubbles=[PortfolioBubble(product_line="Property")]).model_dump()
    assert boardroom._nullify_empty("portfolio_map", kept) is kept


def test_an_empty_widget_is_dropped_even_when_it_explains_itself():
    """A panel that only says "not available here" is a panel to leave out.

    It used to survive on its note, and a board could end up with a whole page of
    them — which is what the reader complained about.
    """
    explained = QuarterlyPerformance(note="No comparable quarters in this scope.").model_dump()
    assert boardroom._nullify_empty("quarterly", QuarterlyPerformance().model_dump()) is None
    assert boardroom._nullify_empty("quarterly", explained) is None


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
    watchlist_stub = _StubPredictor(
        watchlist=Watchlist(
            items=[WatchItem(risk="Rank slipping", premium_exposed_value=4_000_000)]
        )
    )
    never_stub = _StubPredictor()
    monkeypatch.setattr(boardroom, "_CORE_PREDICTOR", core_stub)
    monkeypatch.setattr(
        boardroom,
        "_WIDGET_PREDICTORS",
        {
            "timeline": (timeline_stub, "timeline"),
            "watchlist": (watchlist_stub, "watchlist"),
            "portfolio_map": (never_stub, "portfolio_map"),
            "top_carriers": (never_stub, "top_carriers"),
            "headroom": (never_stub, "headroom"),
            "whitespace": (never_stub, "whitespace"),
            "quarterly": (never_stub, "quarterly"),
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
    assert digest["portfolio_map"] is None
    # The model reported facts, and nothing rated them: the board ranks watch
    # items by the premium they expose and prints no severity at all.
    item = digest["watchlist"]["items"][0]
    assert "priority" not in item
    assert item["premium_exposed_value"] == 4_000_000
    assert item["premium_exposed"] == "£4.0m", "a number arrives with its display text"


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
