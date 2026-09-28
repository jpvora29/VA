"""Setup opens on the latest year, and offers only the quarters that hold data.

The regressions: the form always opened on 2025 (a pinned default), and the Quarter
dropdown offered Q1–Q4 whatever region, country, carrier and year were selected — so a
year still running offered quarters with nothing in them.
"""
from __future__ import annotations

import pandas as pd

from studio.authoring.config import DEFAULT_FILTERS, default_filters
from studio.quarter_scope import frame_quarter_rows, quarter_label, quarters_in

COLUMNS = ("Region", "Country", "Carrier_Group", "Year")
ROWS = [
    ("Asia", "Singapore", "Zurich", 2025, "Q1"),
    ("Asia", "Singapore", "Zurich", 2025, "Q2"),
    ("Asia", "Singapore", "Zurich", 2025, "Q3"),
    ("Asia", "Singapore", "Zurich", 2025, "Q4"),
    ("Asia", "Singapore", "Zurich", 2026, "Q1"),
    ("Asia", "Singapore", "Zurich", 2026, "Q2"),
    ("Asia", "Japan", "Zurich", 2026, "Q3"),
    ("Asia", "Singapore", "AIG", 2026, "Q3"),
]


def test_the_form_opens_on_the_latest_year_the_data_holds():
    options = {"year": [{"label": "2024", "value": 2024}, {"label": "2026", "value": 2026},
                        {"label": "2025", "value": "2025"}]}

    assert default_filters(options)["year"] == 2026
    assert default_filters(options)["carrier"] == DEFAULT_FILTERS["carrier"]


def test_with_no_year_options_the_fallback_default_stands():
    assert default_filters({})["year"] == DEFAULT_FILTERS["year"]


def test_a_running_year_offers_only_the_quarters_it_has():
    where = {"Country": ["Singapore"], "Carrier_Group": "Zurich", "Year": ["2026"]}

    assert quarters_in(ROWS, COLUMNS, where) == ["Q1", "Q2"]


def test_the_quarters_follow_carrier_and_country_too():
    assert quarters_in(ROWS, COLUMNS, {"Carrier_Group": "AIG"}) == ["Q3"]
    assert quarters_in(ROWS, COLUMNS, {"Country": "Japan", "Year": 2026}) == ["Q3"]


def test_an_unset_filter_does_not_narrow():
    assert quarters_in(ROWS, COLUMNS, {"Year": [], "Region": "all"}) == ["Q1", "Q2", "Q3", "Q4"]


def test_a_scope_with_no_data_offers_no_quarter():
    assert quarters_in(ROWS, COLUMNS, {"Year": 2019}) == []


def test_a_derived_quarter_number_reads_as_a_label():
    assert quarter_label(3, native=False) == "Q3"
    assert quarter_label(3.0, native=False) == "Q3"
    assert quarter_label(None, native=False) is None
    assert quarter_label("2025 Q1", native=True) == "2025 Q1"


def test_an_uploaded_dataset_derives_its_quarters_from_the_month():
    frame = pd.DataFrame({
        "Country": ["Singapore", "Singapore", "Japan"],
        "Year": [2026, 2026, 2026],
        "Month_Name": ["January", "May", "November"],
        "Premium": [1.0, 2.0, 3.0],
    })

    columns, rows = frame_quarter_rows(frame)

    assert columns == ("Country", "Year")
    assert quarters_in(rows, columns, {"Country": "Singapore", "Year": 2026}) == ["Q1", "Q2"]


def test_an_uploaded_dataset_without_months_has_no_quarter_rows():
    columns, rows = frame_quarter_rows(pd.DataFrame({"Country": ["X"], "Year": [2026]}))

    assert rows == []
