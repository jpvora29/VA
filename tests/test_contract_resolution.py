"""Tests for query-contract entity resolution (slice 2).

Entity mentions are resolved ONCE, deterministically, against the routed
family's valid values — so the rephraser, rails, and analyst all filter on the
same canonical stored values ("UK" -> "United Kingdom").

Run:  pytest tests/test_contract_resolution.py -q -o pythonpath=.
"""
from __future__ import annotations

from core.agents.common.contract import (
    detect_metrics,
    group_by_of,
    merge_resolved_values,
    resolve_entities,
    resolved_filters_of,
)
from core.agents.common.dimensions import detect_group_by
from core.schemas.routing import QueryEntities, QueryIntent, RoutingContext

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


# ── slice 3: grouping vs filtering (QueryIntent roles) ───────────────────────


def test_detect_group_by_maps_dimension_phrases_to_columns():
    gb = detect_group_by("How does SoW vary across industries in the UK?", "premium")
    assert gb.columns == ["SIC_Major_Class"]
    assert "industries" in gb.dimension_terms

    assert detect_group_by("premium by product for Zurich", "premium").columns == [
        "Product_Line"
    ]
    assert detect_group_by("score per region", "survey").columns == ["Region"]


def test_synonyms_and_for_each_group_but_bare_for_does_not():
    assert detect_group_by("SoW across sectors", "premium").columns == [
        "SIC_Major_Class"
    ]
    assert detect_group_by("premium for each segment", "premium").columns == [
        "Client_Segment"
    ]
    # Bare "for <value>" is a FILTER, not a grouping axis.
    assert detect_group_by("SoW for manufacturing", "premium").columns == []
    # "in the UK" is a filter context, never a group-by.
    assert detect_group_by("Zurich's premium in the UK", "premium").columns == []


def test_grouping_noun_is_not_resolved_as_a_filter():
    # The LLM may bucket the bare grouping word; it must NOT become a filter,
    # nor be surfaced as an unresolved "did you mean…?" term.
    entities = QueryEntities(industries=["industries"])
    resolved, unresolved = resolve_entities(
        entities,
        "premium",
        matcher=_matcher,
        group_by_columns=["SIC_Major_Class"],
        dimension_terms={"industry", "industries"},
    )
    assert resolved == {}
    assert unresolved == []


def test_specific_value_still_filters_on_a_group_by_column():
    # "across industries, focus on manufacturing": SIC is both a group-by axis
    # AND carries a filter value — the value must still resolve.
    entities = QueryEntities(industries=["manufacturing"])
    resolved, unresolved = resolve_entities(
        entities,
        "premium",
        matcher=_matcher,
        group_by_columns=["SIC_Major_Class"],
        dimension_terms={"industry", "industries"},
    )
    assert resolved == {"SIC_Major_Class": ["Mfg - Heavy", "Mfg - Light"]}
    assert unresolved == []


def test_detect_metrics_reads_registry_aliases():
    assert detect_metrics("Zurich's share of wallet across industries", "premium") == [
        "share_of_wallet"
    ]
    assert detect_metrics("how is sentiment trending", "survey") == []


def test_group_by_of_handles_model_dict_and_none():
    ctx = RoutingContext(
        table_family="premium",
        intent_type="new_question",
        query_intent=QueryIntent(group_by=["SIC_Major_Class"]),
    )
    assert group_by_of(ctx) == ["SIC_Major_Class"]
    assert group_by_of(ctx.model_dump()) == ["SIC_Major_Class"]
    assert group_by_of(None) == []
    assert group_by_of({}) == []


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
