"""Computed facts -> the row dicts the charts, insight writer and UI already take.

Run:  pytest tests/analytics/test_tool_rows.py -q
"""
from __future__ import annotations

from core.analytics.tools import column_label, facts_digest, facts_to_rows
from core.analytics.types import AnalyticsFact


def fact(name, value, dims, unit="", rendered="", formula=""):
    return AnalyticsFact(
        name=name, value=value, unit=unit, rendered=rendered, dims=dims, formula=formula
    )


def test_empty_input_is_no_rows():
    assert facts_to_rows([]) == []


def test_one_row_per_cut_with_a_labelled_value_column():
    rows = facts_to_rows(
        [
            fact("breakdown", 150.0, {"Product_Line": "Property"}, unit="Premium"),
            fact("breakdown", 50.0, {"Product_Line": "Cyber"}, unit="Premium"),
        ]
    )
    assert rows == [
        {"Product_Line": "Property", "Premium": 150.0},
        {"Product_Line": "Cyber", "Premium": 50.0},
    ]


def test_different_metrics_on_the_same_cut_share_one_row():
    rows = facts_to_rows(
        [
            fact("breakdown", 150.0, {"Product_Line": "Property"}, unit="Premium"),
            fact("share_of_wallet", 12.4, {"Product_Line": "Property"}),
            fact("yoy", 8.1, {"Product_Line": "Property"}),
        ]
    )
    assert rows == [
        {
            "Product_Line": "Property",
            "Premium": 150.0,
            "Share_of_Wallet_%": 12.4,
            "YoY_%": 8.1,
        }
    ]


def test_a_dimension_every_fact_agrees_on_is_context_not_a_cut():
    # Share of wallet names the carrier; the breakdown does not. With one carrier
    # in scope they describe the SAME product, so they belong on one row.
    rows = facts_to_rows(
        [
            fact("breakdown", 150.0, {"Product_Line": "Property"}, unit="Premium"),
            fact(
                "share_of_wallet",
                12.4,
                {"carrier": "ZURICH GROUP", "Product_Line": "Property"},
            ),
        ]
    )
    assert len(rows) == 1
    assert rows[0]["Premium"] == 150.0
    assert rows[0]["Share_of_Wallet_%"] == 12.4
    assert rows[0]["carrier"] == "ZURICH GROUP"


def test_a_dimension_that_varies_still_splits_rows():
    rows = facts_to_rows(
        [
            fact("rank", 1, {"entity": "ZURICH GROUP", "Product_Line": "Property"}),
            fact("rank", 2, {"entity": "AIG", "Product_Line": "Property"}),
        ]
    )
    assert [row["entity"] for row in rows] == ["ZURICH GROUP", "AIG"]
    assert [row["Rank"] for row in rows] == [1, 2]


def test_column_labels_read_as_business_columns():
    assert column_label(fact("breakdown", 1, {}, unit="Premium")) == "Premium"
    assert column_label(fact("market_presence", 1, {}, unit="Premium")) == "Market_Premium"
    assert column_label(fact("peer_average", 1, {}, unit="Score")) == "Peer_Avg_Score"
    assert column_label(fact("nps", 1, {})) == "NPS"


def test_digest_keeps_the_definition_behind_each_number():
    digest = facts_digest(
        [fact("yoy", 8.1, {"year": 2024}, unit="%", rendered="+8.1%", formula="(a-b)/b")]
    )
    assert digest == [
        {
            "name": "yoy",
            "value": 8.1,
            "unit": "%",
            "rendered": "+8.1%",
            "dims": {"year": 2024},
            "formula": "(a-b)/b",
        }
    ]
