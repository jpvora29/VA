"""Regression tests for pitch-builder number formatting.

The original `parse_signed_number` stripped the decimal point and the minus sign,
which corrupted the KPI premium, YoY growth, and survey score. These tests pin
the corrected behaviour.
"""
from __future__ import annotations

import pytest

from document_builder.helpers.number_formatter import (
    coerce_kpi_number,
    format_money,
    format_pct,
    parse_signed_number,
)
from document_builder.helpers.table_pivot_helper import (
    _format_score,
    _format_year,
)


# --- parse: decimals and signs survive -------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("USD 57,616,719.76", 57616719.76),   # currency code + thousands + cents
        ("$1,234.50", 1234.50),
        ("-9.25%", -9.25),                     # leading minus + percent
        ("+12.5%", 12.5),
        ("8.4", 8.4),                          # bare decimal (survey score)
        ("(1,234.5)", -1234.5),                # accounting-style negative
        ("2024", 2024.0),                      # plain integer (year)
        ("57,500,000", 57500000.0),
        ("", None),
        (None, None),
        ("n/a", None),
    ],
)
def test_parse_preserves_sign_and_decimals(raw, expected):
    assert parse_signed_number(raw) == expected


# --- the three reported symptoms -------------------------------------------
def test_kpi_premium_magnitude():
    # Was rendering as billions/thousands because the decimal was deleted.
    assert format_money(coerce_kpi_number("USD 57,616,719.76")) == "$57.62M"
    assert format_money(57616719.76) == "$57.62M"  # float path unchanged


def test_yoy_growth_sign_and_value():
    # Was rendering as "+925.0" (sign + decimal stripped).
    assert format_pct(coerce_kpi_number("-9.25%")) == "-9.2"
    assert format_pct("+12.5%") == "+12.5"


def test_survey_score_decimal():
    # Was rendering as "84.0".
    assert coerce_kpi_number("8.4") == 8.4
    assert _format_score("8.4") == "8.4"


# --- year cells now actually render -----------------------------------------
def test_format_year_returns_value():
    assert _format_year("2024") == "2024"
    assert _format_year(2023) == "2023"
    assert _format_year("") == "-"
