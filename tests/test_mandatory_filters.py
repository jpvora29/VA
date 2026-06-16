"""Tests for the MandatoryFilterGate (Carrier + Country requirement check).

The gate decides which mandatory roles a turn still lacks after history
inheritance + fuzzy resolution. Columns are derived from the flow registry's
`entity_columns`, so a satisfied role is detected against the exact column the
contract would have filled.

Run:  pytest tests/test_mandatory_filters.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.agents.common.mandatory_filters import MandatoryFilterGate
from core.schemas.routing import RoutingContext, UnresolvedTerm


@pytest.fixture
def gate() -> MandatoryFilterGate:
    return MandatoryFilterGate()


def _ctx(family="premium", resolved=None, **kwargs) -> RoutingContext:
    return RoutingContext(
        table_family=family,
        intent_type="new_question",
        resolved_filters=dict(resolved or {}),
        **kwargs,
    )


def _roles(reqs) -> list[str]:
    return [r.role for r in reqs]


def test_both_missing_for_bare_premium_turn(gate):
    reqs = gate.missing_mandatory_filters(_ctx(resolved={}))
    assert _roles(reqs) == ["carrier", "country"]
    carrier = reqs[0]
    assert carrier.columns == ("Carrier_Group",)
    assert carrier.flow == "gpr"


def test_resolved_carrier_leaves_only_country(gate):
    reqs = gate.missing_mandatory_filters(_ctx(resolved={"Carrier_Group": ["ZURICH GROUP"]}))
    assert _roles(reqs) == ["country"]


def test_nothing_missing_when_both_resolved(gate):
    reqs = gate.missing_mandatory_filters(
        _ctx(resolved={"Carrier_Group": ["ZURICH GROUP"], "Country": ["United Kingdom"]})
    )
    assert reqs == []


def test_inherited_value_satisfies_role(gate):
    ctx = _ctx(resolved={"Country": ["United Kingdom"]}, inherited_carrier="Zurich")
    assert gate.missing_mandatory_filters(ctx) == []


def test_unresolved_mention_defers_to_did_you_mean(gate):
    # Named carrier that failed to resolve -> not a "missing" mandatory filter;
    # the unresolved-entity source handles it.
    ctx = _ctx(
        resolved={"Country": ["United Kingdom"]},
        unresolved_terms=[
            UnresolvedTerm(kind="carrier", term="Zurrich", column="Carrier_Group", flow="gpr")
        ],
    )
    assert gate.missing_mandatory_filters(ctx) == []


def test_fallback_family_never_gates(gate):
    assert gate.missing_mandatory_filters(_ctx(family="fallback", resolved={})) == []


def test_survey_uses_survey_columns(gate):
    reqs = gate.missing_mandatory_filters(_ctx(family="survey", resolved={}))
    assert _roles(reqs) == ["carrier", "country"]
    by_role = {r.role: r for r in reqs}
    assert by_role["carrier"].columns == ("Carrier",)
    assert by_role["country"].columns == ("SurveyCountry",)


def test_both_family_spans_flow_columns(gate):
    reqs = gate.missing_mandatory_filters(_ctx(family="both", resolved={}))
    by_role = {r.role: r for r in reqs}
    # carrier maps to both flows' carrier columns; country to both countries.
    assert set(by_role["carrier"].columns) == {"Carrier_Group", "Carrier"}
    assert set(by_role["country"].columns) == {"Country", "SurveyCountry"}


def test_none_routing_context_is_empty(gate):
    assert gate.missing_mandatory_filters(None) == []
