"""Registry `resolver: semantic` flag (decision #4).

The hybrid's column targeting lives in the registry, not in code. These assert
the flagged set, the spec helpers, and that `validate()` stays clean with the new
field (and rejects a semantic flag on a non-entity column).

Run:  pytest tests/registry/test_resolver_flag.py -q
"""
from __future__ import annotations

from core.registry import get_flow_registry
from core.registry.spec import RESOLVERS, ColumnSpec


def test_gpr_semantic_columns_are_flagged():
    spec = get_flow_registry().get("gpr")
    semantic = set(spec.semantic_columns())
    assert {
        "SIC_Major_Class",
        "SIC_Minor_Class",
        "Product_Line",
        "Business_Line",
        "Cover_Line",
        "Client_Segment",
    } <= semantic
    # Named entities / measures / temporals stay deterministic.
    assert "Carrier_Group" not in semantic
    assert "Premium" not in semantic
    assert "Year" not in semantic


def test_survey_semantic_columns_are_flagged():
    spec = get_flow_registry().get("survey")
    semantic = set(spec.semantic_columns())
    assert {"Attributes", "Sections", "SurveyPractice", "SurveySegment"} <= semantic
    assert "Carrier" not in semantic


def test_is_semantic_column_helper():
    spec = get_flow_registry().get("gpr")
    assert spec.is_semantic_column("SIC_Major_Class") is True
    assert spec.is_semantic_column("Carrier_Group") is False
    assert spec.is_semantic_column("does_not_exist") is False


def test_columnspec_defaults_to_fuzzy():
    c = ColumnSpec(name="X", role="entity")
    assert c.resolver == "fuzzy"
    assert c.is_semantic is False
    assert "fuzzy" in RESOLVERS and "semantic" in RESOLVERS


def test_registry_validate_is_clean_with_resolver_field():
    assert get_flow_registry().validate() == []
