"""The primitive library published as LLM tools.

What matters here is what the model CANNOT say: the argument schemas are built from
the flow registry, so a column or metric the flow does not have is not expressible,
and a definition that belongs to the other flow is not offered.

Run:  pytest tests/analytics/test_tool_catalog.py -q
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.analytics.library import LIBRARY
from core.analytics.sql import flow_spec
from core.analytics.tools import (
    CATALOG,
    catalog_text,
    dimension_columns,
    tool_catalog,
    tool_names,
    tool_schemas,
)


def _schema(flow: str, name: str) -> dict:
    for schema in tool_schemas(flow):
        if schema["function"]["name"] == name:
            return schema["function"]
    raise AssertionError(f"{name} not published for {flow}")


def test_every_catalogued_tool_is_a_real_primitive():
    assert set(CATALOG) <= set(LIBRARY)


def test_catalog_is_split_by_flow_definition():
    gpr, survey = tool_names("gpr"), tool_names("survey")
    # Premium is additive: the peer benchmark is the average of peer TOTALS.
    assert "compute_peer_average_total" in gpr
    assert "compute_peer_average_total" not in survey
    # A score is already an average: the per-response average is the right one.
    assert "compute_peer_average" in survey
    assert "compute_peer_average" not in gpr
    # Domain metrics stay in their domain.
    assert "compute_share_of_wallet" in gpr and "compute_share_of_wallet" not in survey
    assert "compute_nps" in survey and "compute_nps" not in gpr
    # The shared shapes serve both.
    assert {"compute_breakdown", "compute_rank", "compute_yoy"} <= set(gpr) & set(survey)


def test_group_by_enum_is_the_registry_dimension_list():
    enum = _schema("gpr", "compute_breakdown")["parameters"]["properties"]["group_by"][
        "items"
    ]["enum"]
    assert "Product_Line" in enum
    assert "Premium" not in enum          # a measure is computed, never grouped by
    assert "CLIENT_NAME" not in enum      # confidential columns are never a cut


def test_metric_enum_is_the_flow_metric_list():
    enum = _schema("survey", "compute_breakdown")["parameters"]["properties"]["metric"][
        "enum"
    ]
    assert set(enum) == set(flow_spec("survey").metrics)


def test_identity_columns_are_not_offered_as_cuts():
    # ResponseId & friends are declared entities (huge card_cap) — grouping by one
    # returns a row per response, never a business answer.
    assert "ResponseId" not in dimension_columns(flow_spec("survey"))


def test_tools_without_cuts_expose_no_group_by():
    properties = _schema("gpr", "compute_ttm")["parameters"]["properties"]
    assert "group_by" not in properties
    assert "metric" in properties


def test_tuning_options_are_published_only_where_they_apply():
    assert "grain" in _schema("gpr", "compute_period_series")["parameters"]["properties"]
    assert "grain" not in _schema("gpr", "compute_breakdown")["parameters"]["properties"]
    assert "top_n" in _schema("gpr", "find_whitespace")["parameters"]["properties"]


def test_engine_narrows_cuts_to_physically_present_columns():
    # The registry declares BOTH spellings of the survey section column; only the
    # one this warehouse really has may be offered.
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text('CREATE TABLE Carriers (Carrier TEXT, Section TEXT, Score REAL)')
        )
    columns = dimension_columns(flow_spec("survey"), engine=engine)
    assert "Section" in columns
    assert "Sections" not in columns


def test_catalog_text_lists_every_tool_for_the_flow():
    text_menu = catalog_text("gpr")
    assert all(tool.name in text_menu for tool in tool_catalog("gpr"))
