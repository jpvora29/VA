"""`FactFrame` building + column-role detection.

Proves the flow-agnostic seam: the SAME role detector tags GPR (premium) and
survey (perception) columns correctly, so primitives can ask by role without
knowing the flow.

Run:  pytest tests/analytics -q
"""
from __future__ import annotations

from core.analytics.frame import build_frame, detect_roles
from tests.analytics.fixtures import GPR_ROWS, SINGLE_YEAR_ROWS, SURVEY_ROWS


def test_detect_roles_gpr():
    roles = detect_roles(["Carrier_Group", "Country", "Product_Line", "Year", "Premium"])
    assert roles["temporal"] == ("Year",)
    assert roles["geo"] == ("Country",)
    assert roles["product"] == ("Product_Line",)
    assert roles["carrier"] == ("Carrier_Group",)
    assert roles["premium"] == ("Premium",)
    assert "perception" not in roles


def test_detect_roles_survey():
    roles = detect_roles(
        ["Carrier", "SurveyCountry", "SurveyPractice", "Attribute", "Survey_Year", "Score"]
    )
    assert roles["temporal"] == ("Survey_Year",)
    assert roles["geo"] == ("SurveyCountry",)
    assert roles["product"] == ("SurveyPractice", "Attribute")
    assert roles["carrier"] == ("Carrier",)
    assert roles["perception"] == ("Score",)
    assert "premium" not in roles


def test_build_frame_normalizes_scalars():
    frame = build_frame([1, 2, 3])
    assert frame.rows == ({"value": 1}, {"value": 2}, {"value": 3})
    assert frame.roles == {}


def test_frame_distinct_periods():
    frame = build_frame(GPR_ROWS)
    assert frame.distinct("temporal") == {"2023", "2024"}

    single = build_frame(SINGLE_YEAR_ROWS)
    assert single.distinct("temporal") == {"2024"}


def test_frame_columns_by_role_survey():
    frame = build_frame(SURVEY_ROWS)
    assert frame.columns("perception") == ("Score",)
    assert set(frame.columns("product")) == {"SurveyPractice", "Attribute"}
