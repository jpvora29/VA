"""A partial year is compared with the SAME span of the year before.

The chat's position table, its YoY column, the "What moved" waterfall and the
growth claims all read `compute_contribution` and the prior-year position pack.
Both used to take the WHOLE prior year, so a warehouse loaded through May read a
flat book as a collapse. Checked on both executors (SQL and pandas).

2024: $1M a month, all twelve months, plus a Peers row so rank/share exist.
2025: $1M a month, January to May only — the same run-rate, five months in.

Run:  pytest tests/analytics/test_like_for_like_years.py -q -o pythonpath=.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from core.analytics import PrimitiveArgs
from core.analytics.frames import frame_source
from core.analytics.movement import compute_contribution
from core.analytics.periods import PeriodsThrough, span_label
from core.analytics.positioning import build_positioning_comparison

_COLUMNS = ["Carrier_Group", "Country", "Product_Line", "Year", "Billing_Date", "Premium"]


def _rows(last_month_2025: int):
    rows = []
    for carrier, rate in (("Zurich", 1e6), ("AIG", 2e6)):
        for month in range(1, 13):
            rows.append((carrier, "Canada", "Property", 2024, f"2024-{month:02d}-15", rate))
        for month in range(1, last_month_2025 + 1):
            rows.append((carrier, "Canada", "Property", 2025, f"2025-{month:02d}-15", rate))
    return rows


def _engine(rows):
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE GPR (Carrier_Group TEXT, Country TEXT, Product_Line TEXT,"
                          " Year INTEGER, Billing_Date TEXT, Premium REAL)"))
        conn.execute(text("CREATE TABLE Peers (Carrier_Group TEXT, Overall_Peer_Group TEXT,"
                          " Country TEXT)"))
        conn.execute(text("INSERT INTO Peers VALUES ('ZURICH','AIG','Canada')"))
        conn.execute(text("INSERT INTO GPR VALUES (:a,:b,:c,:d,:e,:f)"),
                     [dict(zip("abcdef", row)) for row in rows])
    return eng


def _frames(rows):
    return frame_source({"GPR": pd.DataFrame(rows, columns=_COLUMNS)})


@pytest.fixture(params=["sql", "pandas"])
def executor(request):
    return request.param


def _source(executor, rows):
    return _engine(rows) if executor == "sql" else _frames(rows)


def _headline(source):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Carrier_Group": "Zurich", "Country": "Canada", "Year": 2025})
    facts = compute_contribution(args, engine=source)
    return facts[0], facts[1:]


def test_a_partial_year_is_compared_with_the_same_months_last_year(executor):
    headline, slices = _headline(_source(executor, _rows(last_month_2025=5)))
    # Jan-May 2025 ($5M) against Jan-May 2024 ($5M): flat, not -58%.
    assert headline.value == pytest.approx(0.0)
    assert headline.dims["through"] == "Jan-May"
    assert slices[0].dims["percent"] == pytest.approx(0.0)


def test_a_complete_year_is_compared_whole(executor):
    headline, _ = _headline(_source(executor, _rows(last_month_2025=12)))
    assert headline.value == pytest.approx(0.0)
    assert "through" not in headline.dims


def test_the_position_table_reads_flat_on_a_partial_year(executor):
    pack = build_positioning_comparison(
        dimension="Product_Line",
        filters={"Carrier_Group": "Zurich", "Country": "Canada", "Year": 2025},
        subject="Zurich", engine=_source(executor, _rows(last_month_2025=5)))
    (property_line,) = pack.positions
    assert property_line.premium_change_percent == pytest.approx(0.0)
    # Last year's standing is taken over the same five months, so it is there.
    assert property_line.prior_share_of_wallet == pytest.approx(property_line.share_of_wallet)


def test_the_span_is_named_the_way_a_reader_says_it():
    assert span_label("month", 5) == "Jan-May"
    assert span_label("quarter", 2) == "Q1-Q2"
    assert span_label("quarter", None) == ""
    assert str(PeriodsThrough("quarter", 3)) == "Q1-Q3"
