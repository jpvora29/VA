"""Step-1 parity proof: the flow registry returns today's hardcoded output.

Asserts the registry-backed `mcp.tools.get_valid_values` / `get_definitions` /
`_SCHEMA_TABLES_BY_FLOW` equal the legacy `GetValidData` dicts byte-for-byte, so
introducing the registry seam is a zero-behavior-change move. Plus registry
health (`validate()`) and the alias resolver.

Run:  pytest tests/registry -q
"""
from __future__ import annotations

import pytest

from core.data.valid_values import GetValidData
from core.mcp import tools as mcp_tools
from core.registry import get_flow_registry


# ---- parity: valid_values -------------------------------------------------

@pytest.mark.parametrize(
    "flow, legacy",
    [
        ("survey", GetValidData.valid_values),
        ("gpr", GetValidData.valid_values_gpr),
        ("gimmi", GetValidData.gimmi_valid_values),
    ],
)
def test_valid_values_parity(flow, legacy):
    assert mcp_tools.get_valid_values(flow) == legacy


@pytest.mark.parametrize(
    "flow, legacy",
    [
        ("survey", GetValidData.definitions),
        ("gpr", GetValidData.definitions_gpr),
        ("gimmi", GetValidData.gimmi_definitions),
    ],
)
def test_definitions_parity(flow, legacy):
    assert mcp_tools.get_definitions(flow) == legacy


def test_unknown_flow_falls_back_to_survey():
    # Former behavior: gpr/gimmi explicit, everything else -> survey dicts.
    assert mcp_tools.get_valid_values("nope") == GetValidData.valid_values
    assert mcp_tools.get_definitions("nope") == GetValidData.definitions


# ---- parity: schema table slices -----------------------------------------

def test_schema_tables_parity():
    assert mcp_tools._SCHEMA_TABLES_BY_FLOW == {
        "survey": ["Carriers", "Peers"],
        "gpr": ["GPR", "Peers"],
        "gimmi": ["GIMMI"],
    }


# ---- registry health ------------------------------------------------------

def test_registry_validate_is_clean():
    issues = get_flow_registry().validate()
    assert issues == [], "\n".join(issues)


def test_allowed_tables():
    reg = get_flow_registry()
    assert reg.get("gpr").allowed_tables == ("GPR", "Peers")
    assert reg.get("survey").allowed_tables == ("Carriers", "Peers")
    assert reg.get("gimmi").allowed_tables == ("GIMMI",)


# ---- semantic helpers -----------------------------------------------------

def test_resolve_alias():
    gpr = get_flow_registry().get("gpr")
    assert gpr.resolve_alias("gross premium") == "premium"      # metric alias
    assert gpr.resolve_alias("sow") == "share_of_wallet"        # metric alias
    assert gpr.resolve_alias("carrier") == "Carrier_Group"      # column alias
    assert gpr.resolve_alias("nonsense") is None


def test_card_cap_gate_metadata():
    gpr = get_flow_registry().get("gpr")
    # High-card entity columns carry a low cap so the step-3 gate fuzzy-resolves
    # them; low-card columns inject in full.
    assert gpr.card_cap("Carrier_Group") == 8
    assert gpr.card_cap("Country") == 30
    assert get_flow_registry().get("gpr").column("CLIENT_NAME").confidential is True
