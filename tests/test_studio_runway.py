"""Runway to Top 5 Average — each product line's own five largest carriers, never the peers.

The Carrier-breakdown page's last column is "Runway to Top 5 Average": the carrier's premium
in a product line minus the average premium of THAT LINE's five largest carriers in the
country, ranked by their premium in the line (the subject eligible). Each row has its own
five. It must not move when the author picks a different peer group.
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
    """``{product: (top-5 average, runway)}`` straight from SQL, ranked per product."""
    with sqlite3.connect(engine.url.database) as conn:
        cells = list(conn.execute(
            "SELECT Product_Line, Carrier_Group, SUM(Premium) FROM GPR WHERE Country = ? "
            "AND Year = ? GROUP BY 1, 2", (country, year)))
    by_product = {}
    for product, carrier, value in cells:
        by_product.setdefault(product, {})[carrier] = value or 0.0
    out = {}
    for product, by_carrier in by_product.items():
        top = sorted(by_carrier.values(), reverse=True)[:5]
        avg = sum(top) / len(top)
        out[product] = (avg, by_carrier.get(subject, 0.0) - avg)
    return out


def test_runway_is_measured_against_each_products_own_top_five(engine):
    expected = _manual_runway(engine, "Singapore", 2025, "Zurich")
    f = _resolve_filters({"carrier": "Zurich", "country": "Singapore", "year": 2025})
    rows = product_breakdown_rows("gpr", f, engine, "Zurich", top=10)
    assert rows
    for row in rows:
        avg, runway = expected[row["name"]]
        assert row["peer_gwp"] == pytest.approx(avg)
        assert row["runway"] == pytest.approx(runway)
        assert row["runway"] == pytest.approx(row["gwp"] - row["peer_gwp"])


def test_the_benchmark_set_differs_by_product_line():
    """A carrier that leads one line can be absent from another — each line ranks its own."""
    property_line = {"A": 100.0, "B": 90.0, "C": 80.0, "D": 70.0, "E": 60.0, "F": 1.0}
    marine_line = {"F": 50.0, "G": 40.0, "A": 0.0}
    assert product_top_average(property_line) == pytest.approx(80.0)
    # F writes 1 in property but leads marine; fewer than five average the ones there are.
    assert product_top_average(marine_line) == pytest.approx(30.0)
    assert product_top_average({}) == 0.0


def test_runway_does_not_move_with_the_selected_peers(engine):
    """Peers ride on the result, never in the filters this reads — pin it anyway."""
    from studio.compute import compute_overall
    from studio.template_fill.grids import grid_values  # noqa: F401 - the consumer exists

    base = {"carrier": "Zurich", "country": ["Singapore"], "year": [2025]}
    plain = compute_overall(filters=base, engine=engine)
    pinned = compute_overall(filters=base, engine=engine,
                             peers=["AIG", "Chubb", "QBE", "Sompo", "MS&AD"])
    f = {**plain.resolved_filters, "Country": "Singapore", "Year": 2025}
    assert product_breakdown_rows("gpr", f, plain.engine, "Zurich") == \
        product_breakdown_rows("gpr", {**pinned.resolved_filters, "Country": "Singapore",
                                       "Year": 2025}, pinned.engine, "Zurich")
