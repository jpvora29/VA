"""Tests for the MandatoryFilterGate — is this turn scoped enough to run?

The bar is ANY ONE of carrier, country or year, present as a resolved filter, an
inherited value, or a bare mention. Only a turn naming none of the three is
stopped, and it is then asked for the two roles it can be asked for. Columns are
derived from the flow registry's `entity_columns`, so a satisfied role is
detected against the exact column the contract would have filled.

`tests/test_clarify_flow.py` covers the same rule from the clarify node's side;
this file is about the gate's own shape — which columns and flow each
`FilterRequirement` carries.

Run:  pytest tests/test_mandatory_filters.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.agents.common.mandatory_filters import MandatoryFilterGate
from core.schemas.routing import QueryEntities, RoutingContext, UnresolvedTerm


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


def test_a_resolved_carrier_alone_scopes_the_turn(gate):
    """It used to leave "country" to ask for — a question that had already said
    what it was about was stopped for something the analyst can answer without."""
    ctx = _ctx(resolved={"Carrier_Group": ["ZURICH GROUP"]})
    assert gate.has_scope(ctx)
    assert gate.missing_mandatory_filters(ctx) == []


def test_a_resolved_country_alone_scopes_the_turn(gate):
    assert gate.missing_mandatory_filters(_ctx(resolved={"Country": ["United Kingdom"]})) == []


def test_nothing_missing_when_both_resolved(gate):
    reqs = gate.missing_mandatory_filters(
        _ctx(resolved={"Carrier_Group": ["ZURICH GROUP"], "Country": ["United Kingdom"]})
    )
    assert reqs == []


def test_a_year_scopes_the_turn_without_being_askable(gate):
    """A year auto-defaults, so it is never asked for — but naming one scopes."""
    assert gate.missing_mandatory_filters(_ctx(timeframe_hint="2024")) == []
    assert gate.missing_mandatory_filters(_ctx(resolved={"Year": ["2024"]})) == []


def test_a_product_alone_does_not_scope_the_turn(gate):
    """Carrier / country / year say WHAT a question is about; a product narrows it."""
    reqs = gate.missing_mandatory_filters(_ctx(resolved={"Product_Line": ["Property"]}))
    assert _roles(reqs) == ["carrier", "country"]


def test_inherited_value_satisfies_role(gate):
    ctx = _ctx(resolved={"Country": ["United Kingdom"]}, inherited_carrier="Zurich")
    assert gate.missing_mandatory_filters(ctx) == []


def test_unresolved_mention_defers_to_did_you_mean(gate):
    """A named carrier that failed to resolve is asked about ONCE, by the
    grounded "did you mean...?" source — never also as a missing filter."""
    ctx = _ctx(
        resolved={},
        unresolved_terms=[
            UnresolvedTerm(kind="carrier", term="Zurrich", column="Carrier_Group", flow="gpr")
        ],
    )
    assert _roles(gate.missing_mandatory_filters(ctx)) == ["country"]


def test_a_mention_scopes_the_turn_even_when_it_did_not_resolve(gate):
    ctx = _ctx(resolved={}, entities=QueryEntities(carriers=["Zurrich"]))
    assert gate.has_scope(ctx)
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
