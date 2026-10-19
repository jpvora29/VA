"""Runway to Top 5 Average — each product line's own five largest carriers, never the peers.

The Carrier-breakdown page's last column is "Runway to Top 5 Average": the carrier's premium
in a product line minus the average premium of THAT LINE's five largest carriers in the
country, ranked by their premium in the line. The carrier is never part of its own
benchmark: when it is one of the five, the other four are averaged. Each row has its own
five. It must not move when the author picks a different peer group.

The "Peer GWP" column beside it is a different number: the mean premium in the line of the
carrier's peer set for the country (pinned, else the approved Peers-table group).
"""
from __future__ import annotations

import sqlite3

import pytest

from studio.compute import _resolve_filters, product_breakdown_rows, product_top_average


@pytest.fixture
def engine():
    from studio.data import get_engine

    return get_engine()


def _manual_runway(engine, country: str, year: int, subject: str):
    """``{product: (benchmark, runway)}`` straight from SQL, ranked per product."""
    with sqlite3.connect(engine.url.database) as conn:
        cells = list(conn.execute(
            "SELECT Product_Line, Carrier_Group, SUM(Premium) FROM GPR WHERE Country = ? "
            "AND Year = ? GROUP BY 1, 2", (country, year)))
    by_product = {}
    for product, carrier, value in cells:
        by_product.setdefault(product, {})[carrier] = value or 0.0
    out = {}
    for product, by_carrier in by_product.items():
        top = sorted(by_carrier.items(), key=lambda kv: kv[1], reverse=True)[:5]
        others = [v for c, v in top if c.lower() != subject.lower()]
        if not others:
            out[product] = (None, None)
            continue
        avg = sum(others) / len(others)
        out[product] = (avg, by_carrier.get(subject, 0.0) - avg)
    return out


def test_runway_is_measured_against_each_products_own_top_five(engine):
    expected = _manual_runway(engine, "Singapore", 2025, "Zurich")
    f = _resolve_filters({"carrier": "Zurich", "country": "Singapore", "year": 2025})
    rows = product_breakdown_rows("gpr", f, engine, "Zurich", top=10)
    assert rows
    for row in rows:
        avg, runway = expected[row["name"]]
        if avg is None:
            assert row["top5_avg"] is None and row["runway"] is None
            continue
        assert row["top5_avg"] == pytest.approx(avg)
        assert row["runway"] == pytest.approx(runway)
        assert row["runway"] == pytest.approx(row["gwp"] - row["top5_avg"])


def test_subject_outside_the_top_five_is_measured_against_all_five():
    line = {"A": 100.0, "B": 90.0, "C": 80.0, "D": 70.0, "E": 60.0, "Me": 10.0}
    assert product_top_average(line, "Me") == pytest.approx(80.0)


def test_subject_inside_the_top_five_is_left_out_and_the_other_four_averaged():
    line = {"A": 100.0, "Me": 90.0, "C": 80.0, "D": 70.0, "E": 60.0, "F": 50.0}
    # The other four of the top five — F (sixth) is NOT promoted to fill the gap.
    assert product_top_average(line, "Me") == pytest.approx((100 + 80 + 70 + 60) / 4)
    # Names match the way the rest of the page matches them: case-insensitively.
    assert product_top_average(line, "me") == pytest.approx((100 + 80 + 70 + 60) / 4)


def test_the_benchmark_set_differs_by_product_line():
    """A carrier that leads one line can be absent from another — each line ranks its own."""
    property_line = {"A": 100.0, "B": 90.0, "C": 80.0, "D": 70.0, "E": 60.0, "F": 1.0}
    marine_line = {"F": 50.0, "G": 40.0, "A": 0.0}
    assert product_top_average(property_line, "F") == pytest.approx(80.0)
    # F leads marine; fewer than five average the ones there are, F itself left out.
    assert product_top_average(marine_line, "F") == pytest.approx(20.0)


def test_a_line_only_the_subject_writes_has_no_benchmark():
    assert product_top_average({"Me": 50.0}, "Me") is None
    assert product_top_average({}, "Me") is None


def _manual_peer_mean(engine, country: str, year: int, peers) -> dict:
    """``{product: mean premium of the peers writing it}`` straight from SQL."""
    marks = ", ".join("?" for _ in peers)
    with sqlite3.connect(engine.url.database) as conn:
        cells = list(conn.execute(
            f"SELECT Product_Line, Carrier_Group, SUM(Premium) FROM GPR WHERE Country = ? "
            f"AND Year = ? AND Carrier_Group IN ({marks}) GROUP BY 1, 2",
            (country, year, *peers)))
    by_product = {}
    for product, _carrier, value in cells:
        by_product.setdefault(product, []).append(value or 0.0)
    return {p: sum(v) / len(v) for p, v in by_product.items()}


def _approved_peers(engine, carrier: str, country: str):
    with sqlite3.connect(engine.url.database) as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT Peers FROM Peers WHERE Carrier_Group = ? AND Country = ?",
            (carrier, country))]


def test_peer_gwp_is_the_mean_of_the_approved_peer_set(engine):
    peers = _approved_peers(engine, "Zurich", "Singapore")
    assert peers
    expected = _manual_peer_mean(engine, "Singapore", 2025, peers)
    f = _resolve_filters({"carrier": "Zurich", "country": "Singapore", "year": 2025})
    rows = product_breakdown_rows("gpr", f, engine, "Zurich", top=10)
    for row in rows:
        assert row["peer_gwp"] == pytest.approx(expected[row["name"]])


def test_pinned_peers_move_peer_gwp_but_never_the_runway(engine):
    f = _resolve_filters({"carrier": "Zurich", "country": "Singapore", "year": 2025})
    pinned = ("QBE", "Sompo", "MS&AD", "Tokio Marine", "Liberty")
    plain = product_breakdown_rows("gpr", f, engine, "Zurich", top=10)
    custom = product_breakdown_rows("gpr", f, engine, "Zurich", top=10, peers=pinned)
    expected = _manual_peer_mean(engine, "Singapore", 2025, pinned)
    assert [r["runway"] for r in plain] == [r["runway"] for r in custom]
    assert [r["top5_avg"] for r in plain] == [r["top5_avg"] for r in custom]
    for row in custom:
        assert row["peer_gwp"] == pytest.approx(expected.get(row["name"]))             if row["name"] in expected else row["peer_gwp"] is None
    assert [r["peer_gwp"] for r in plain] != [r["peer_gwp"] for r in custom]


def test_breakdown_grid_averages_each_markets_own_pinned_peers():
    from dataclasses import dataclass
    from typing import Optional

    from studio.template_fill.grids import _market_peers

    @dataclass(frozen=True)
    class Run:
        peers: Optional[tuple] = None
        peers_by_country: Optional[dict] = None
        survey_peers: Optional[tuple] = None
        survey_peers_by_country: Optional[dict] = None

    run = Run(peers=("A", "B", "C", "D", "E", "F"),
              peers_by_country={"Singapore": ("A", "B"), "Japan": ()})
    assert _market_peers(run, "Singapore") == ("A", "B")
    assert _market_peers(run, "Japan") is None           # resolves its own approved group
    assert _market_peers(Run(peers=("A", "B")), "Japan") == ("A", "B")   # flat pin
    assert _market_peers(Run(), "Japan") is None
