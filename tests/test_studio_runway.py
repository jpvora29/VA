"""Runway to Top 5 Average — the country's five largest carriers, never the peer group.

The Carrier-breakdown page's last column is "Runway to Top 5 Average": the carrier's premium
in a product line minus the average premium, in that line, of the FIVE LARGEST CARRIERS IN
THE COUNTRY. One fixed set of five for every row; a leader writing nothing in a line counts
as zero. It must not move when the author picks a different peer group.
"""
from __future__ import annotations

import sqlite3

import pytest

from studio.compute import _resolve_filters, product_breakdown_rows, top_carriers


@pytest.fixture
def engine():
    from studio.data import get_engine

    return get_engine()


def _manual_runway(engine, country: str, year: int, subject: str):
    with sqlite3.connect(engine.url.database) as conn:
        leaders = [r[0] for r in conn.execute(
            "SELECT Carrier_Group FROM GPR WHERE Country = ? AND Year = ? GROUP BY Carrier_Group "
            "ORDER BY SUM(Premium) DESC, Carrier_Group LIMIT 5", (country, year))]
        cells = {(p, c): v for p, c, v in conn.execute(
            "SELECT Product_Line, Carrier_Group, SUM(Premium) FROM GPR WHERE Country = ? "
            "AND Year = ? GROUP BY 1, 2", (country, year))}
    products = {p for p, _ in cells}
    return leaders, {p: cells.get((p, subject), 0.0)
                     - sum(cells.get((p, c), 0.0) for c in leaders) / 5 for p in products}


def test_runway_is_measured_against_the_countrys_top_five(engine):
    leaders, expected = _manual_runway(engine, "Singapore", 2025, "Zurich")
    f = _resolve_filters({"carrier": "Zurich", "country": "Singapore", "year": 2025})
    assert list(top_carriers("gpr", {k: v for k, v in f.items() if k != "Carrier_Group"},
                             engine)) == leaders
    rows = product_breakdown_rows("gpr", f, engine, "Zurich", top=10)
    assert rows
    for row in rows:
        assert row["runway"] == pytest.approx(expected[row["name"]])
        assert row["runway"] == pytest.approx(row["gwp"] - row["peer_gwp"])


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
