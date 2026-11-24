"""Phase 2 step 1: the TurnSpec shadow — one interpretation, its contradictions logged."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from core.turn import TurnSpec, build_turn_spec, find_disagreements
from core.turn.node import turn_spec_node


def routing(
    family="premium",
    depth="lookup",
    shape="analyst",
    presentation="prose",
    filters=None,
    unresolved=(),
    inherited_year=None,
    directive_depth="analyst",
):
    return {
        "table_family": family,
        "analysis_depth": depth,
        "output_directives": {
            "shape": shape,
            "presentation": presentation,
            "depth": directive_depth,
        },
        "resolved_filters": filters or {},
        "unresolved_terms": [{"term": t} for t in unresolved],
        "inherited_year": inherited_year,
    }


def rules(spec):
    return [d.rule for d in find_disagreements(spec)]


# --------------------------------------------------------------------------- #
# Building the spec
# --------------------------------------------------------------------------- #


def test_the_spec_records_each_components_decision():
    spec = build_turn_spec(
        "How was Zurich's performance in Singapore in 2025?",
        routing(
            depth="analytical", filters={"Country": ["Singapore"], "Year": ["2025"]}
        ),
    )
    assert spec.family == "premium" and spec.depth == "analytical"
    assert spec.operation == "performance_assessment"
    assert spec.sources == ("gpr",)
    assert "annual_movement" in spec.requirements
    assert spec.period_named
    assert spec.scope_dict()["Country"] == ("Singapore",)


def test_a_premium_only_restriction_narrows_a_hybrid_turn():
    spec = build_turn_spec(
        "Zurich performance in Japan, premium only", routing(family="both")
    )
    assert spec.sources == ("gpr",)


def test_a_period_counts_as_named_when_it_was_inherited():
    spec = build_turn_spec("and by product?", routing(inherited_year="2024"))
    assert spec.period_named


def test_the_dict_form_is_json_safe():
    import json

    spec = build_turn_spec(
        "Premium for Chubb", routing(filters={"Carrier_Group": ["CHUBB"]})
    )
    data = json.loads(json.dumps(spec.as_dict()))
    assert data["scope"] == {"Carrier_Group": ["CHUBB"]}


# --------------------------------------------------------------------------- #
# Disagreements
# --------------------------------------------------------------------------- #


def _spec(**overrides):
    base = dict(
        question="q",
        family="premium",
        depth="lookup",
        operation="lookup",
        shape="direct",
        presentation="prose",
        sources=("gpr",),
    )
    return TurnSpec(**{**base, **overrides})


def test_a_consistent_turn_has_no_disagreements():
    assert rules(_spec()) == []


def test_a_lookup_that_owes_requirements_is_flagged():
    assert "lookup_route_owes_requirements" in rules(
        _spec(operation="performance_assessment", requirements=("annual_movement",))
    )


def test_a_full_analysis_shape_on_the_single_query_rail_is_flagged():
    assert rules(_spec(shape="analyst")) == ["shape_exceeds_depth"]


def test_a_full_analysis_shape_with_no_prose_is_not_flagged():
    assert rules(_spec(shape="analyst", presentation="table_only")) == []


def test_a_one_line_answer_on_the_analyst_route_is_flagged():
    assert rules(_spec(depth="analytical")) == ["direct_shape_on_analyst_route"]


def test_a_restriction_its_route_cannot_reach_is_flagged():
    assert rules(_spec(family="survey", sources=("gpr",))) == [
        "restriction_outside_family"
    ]


def test_unresolved_names_reaching_the_router_are_flagged():
    assert rules(_spec(unresolved=("Zurch",))) == ["unresolved_terms_routed"]


def test_an_off_topic_route_with_filters_is_flagged():
    assert rules(
        _spec(family="fallback", sources=(), scope=(("Country", ("Japan",)),))
    ) == ["fallback_with_scope"]


def test_the_motivating_mismatch_is_caught_end_to_end():
    """A performance question the depth model called 'lookup': one query, but
    the writer is told to produce a full analysis and the contract owes four
    requirements."""
    spec = build_turn_spec(
        "How was Zurich's performance in Singapore in 2025?",
        routing(depth="lookup", shape="analyst"),
    )
    assert {"lookup_route_owes_requirements", "shape_exceeds_depth"} <= set(rules(spec))


# --------------------------------------------------------------------------- #
# The shadow node
# --------------------------------------------------------------------------- #


def _state(question, rc):
    return {"messages": [HumanMessage(content=question)], "routing_context": rc}


def test_the_node_stores_the_spec_and_its_disagreements():
    out = turn_spec_node(_state("Premium for Chubb", routing(shape="analyst")))
    assert out["turn_spec"]["family"] == "premium"
    assert [d["rule"] for d in out["turn_spec"]["disagreements"]] == [
        "shape_exceeds_depth"
    ]


def test_the_node_never_fails_a_turn(monkeypatch):
    import core.turn.node as node

    monkeypatch.setattr(
        node, "build_turn_spec", lambda *a: (_ for _ in ()).throw(ValueError("x"))
    )
    assert turn_spec_node(_state("q", routing())) == {"turn_spec": None}


def test_the_node_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("TURN_SPEC", "off")
    assert turn_spec_node(_state("q", routing())) == {"turn_spec": None}


def test_the_node_reads_a_pydantic_routing_context():
    from core.schemas.routing import RoutingContext

    rc = RoutingContext(
        table_family="premium",
        analysis_depth="lookup",
        intent_type="new_question",
        resolved_filters={"Country": ["Japan"]},
    )
    out = turn_spec_node(_state("Premium in Japan", rc))
    assert out["turn_spec"]["scope"] == {"Country": ["Japan"]}


def test_the_spec_sits_between_the_hitl_gates_and_the_router():
    from core.graph.main import LangGraph

    graph = LangGraph(checkpointer=None).create_workflow().get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("custom_peer_gate", "turn_spec") in edges
    assert ("turn_spec", "router") in edges
