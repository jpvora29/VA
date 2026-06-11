"""Tests for query-contract entity resolution (slice 2).

Entity mentions are resolved ONCE, deterministically, against the routed
family's valid values — so the rephraser, rails, and analyst all filter on the
same canonical stored values ("UK" -> "United Kingdom").

Run:  pytest tests/test_contract_resolution.py -q -o pythonpath=.
"""
from __future__ import annotations

from core.agents.common.contract import (
    merge_resolved_values,
    resolve_entities,
    resolved_filters_of,
)
from core.schemas.routing import QueryEntities, RoutingContext

# (flow, column, lowercased term) -> stored values. Anything absent is a miss.
_MATCHES = {
    ("gpr", "Carrier_Group", "zurich"): ["ZURICH GROUP"],
    ("gpr", "Country", "uk"): ["United Kingdom"],
    ("gpr", "SIC_Major_Class", "manufacturing"): ["Mfg - Heavy", "Mfg - Light"],
    ("survey", "Carrier", "zurich"): ["Zurich"],
    ("survey", "SurveyCountry", "uk"): ["United Kingdom"],
}


def _matcher(flow: str, column: str, term: str):
    return _MATCHES.get((flow, column, term.lower()), [])


def test_premium_family_resolves_against_gpr_columns():
    entities = QueryEntities(carriers=["Zurich"], countries=["UK"])
    resolved, unresolved = resolve_entities(entities, "premium", matcher=_matcher)
    assert resolved == {
        "Carrier_Group": ["ZURICH GROUP"],
        "Country": ["United Kingdom"],
    }
    assert unresolved == []


def test_both_family_resolves_against_both_flows():
    entities = QueryEntities(carriers=["Zurich"])
    resolved, _ = resolve_entities(entities, "both", matcher=_matcher)
    # The same mention grounds the GPR and the survey carrier columns.
    assert resolved == {"Carrier_Group": ["ZURICH GROUP"], "Carrier": ["Zurich"]}


def test_miss_is_surfaced_as_unresolved_not_dropped():
    entities = QueryEntities(countries=["Atlantis"])
    resolved, unresolved = resolve_entities(entities, "premium", matcher=_matcher)
    assert resolved == {}
    assert len(unresolved) == 1
    u = unresolved[0]
    assert (u.kind, u.term, u.column, u.flow) == (
        "country", "Atlantis", "Country", "gpr",
    )


def test_industry_maps_via_registry_alias_and_keeps_concept_fanout():
    entities = QueryEntities(industries=["manufacturing"])
    resolved, _ = resolve_entities(entities, "premium", matcher=_matcher)
    # 'industry' is not in gpr entity_columns — the alias on SIC_Major_Class
    # routes it; a concept term legitimately fans out to several classes.
    assert resolved == {"SIC_Major_Class": ["Mfg - Heavy", "Mfg - Light"]}


def test_marsh_is_never_carrier_resolved():
    entities = QueryEntities(carriers=["Marsh", "Zurich"])
    resolved, unresolved = resolve_entities(entities, "premium", matcher=_matcher)
    assert resolved == {"Carrier_Group": ["ZURICH GROUP"]}
    assert unresolved == []  # the broker is skipped, not flagged


def test_measure_words_bucketed_as_entities_are_skipped_not_clarified():
    # The context filler sometimes mis-buckets a measure ('appetite' == share
    # of portfolio, 'sow' == share of wallet) into an entity bucket. A measure
    # is not a filter value: it must NOT be flagged unresolved (which would
    # raise a spurious "did you mean product 'appetite'?" clarify card).
    for term in ("appetite", "sow", "share of wallet", "premium"):
        entities = QueryEntities(products=[term], segments=[term])
        resolved, unresolved = resolve_entities(entities, "premium", matcher=_matcher)
        assert resolved == {}, term
        assert unresolved == [], term


def test_years_and_fallback_family_resolve_nothing():
    entities = QueryEntities(years=["2024"], carriers=["Zurich"])
    assert resolve_entities(entities, "fallback", matcher=_matcher) == ({}, [])
    resolved, _ = resolve_entities(entities, "premium", matcher=_matcher)
    assert "2024" not in str(resolved)  # years are the timeframe slice's job


def test_merge_resolved_values_unions_in_order():
    base = {"Country": ["United Kingdom"]}
    extra = {"Country": ["United Kingdom", "Canada"], "Carrier_Group": ["AXA"]}
    assert merge_resolved_values(base, extra) == {
        "Country": ["United Kingdom", "Canada"],
        "Carrier_Group": ["AXA"],
    }


def test_resolved_filters_of_handles_model_dict_and_none():
    ctx = RoutingContext(
        table_family="premium",
        intent_type="new_question",
        resolved_filters={"Country": ["United Kingdom"]},
    )
    assert resolved_filters_of(ctx) == {"Country": ["United Kingdom"]}
    assert resolved_filters_of(ctx.model_dump()) == {"Country": ["United Kingdom"]}
    assert resolved_filters_of(None) == {}
    assert resolved_filters_of({}) == {}
