"""What a checkpoint is allowed to carry, and what happens when it carries it.

LangGraph serializes graph state with msgpack. For a type it does not recognise
it currently deserializes anyway while logging

    Deserializing unregistered type core.schemas.routing.RoutingContext from
    checkpoint. This will be blocked in a future version.

That is a forward-compatibility warning, not noise. When the release it promises
lands, an un-allowlisted `RoutingContext` stops round-tripping — and a resumed
conversation silently loses the filters, inheritance and directives that live on
it, which is the worst possible thing for it to lose quietly.

Run:  pytest tests/test_checkpoint_serde.py -q -o pythonpath=.
"""
from __future__ import annotations

import logging

import pytest

from core.graph.checkpointer import _serializer, _state_types
from core.schemas.routing import (
    OutputDirectives,
    QueryEntities,
    QueryIntent,
    RoutingContext,
    UnresolvedTerm,
)


@pytest.fixture
def routing_context() -> RoutingContext:
    """A fully populated context — every nested model, not just the outer one."""
    rc = RoutingContext(table_family="both", intent_type="new_question")
    rc.entities = QueryEntities(
        carriers=["ZURICH GROUP"], countries=["Canada"], years=["2025"]
    )
    rc.query_intent = QueryIntent(group_by=["Product_Line"], metrics=["premium"])
    rc.output_directives = OutputDirectives(charts="none", presentation="table_only")
    rc.unresolved_terms = [
        UnresolvedTerm(kind="carrier", term="notacarrier",
                       column="Carrier_Group", flow="gpr")
    ]
    rc.resolved_filters = {"Year": ["2025"], "Carrier_Group": ["ZURICH GROUP"]}
    rc.analysis_depth = "analytical"
    return rc


def _warnings_while(serde, payload) -> tuple[object, list[str]]:
    """Round-trip `payload`, capturing what the serializer logged while doing it."""
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            # `getMessage()` already applies `record.args`. Applying them again
            # raises, and `logging` swallows a handler's exception — which makes
            # every "no warning was logged" assertion pass for the wrong reason.
            records.append(record.getMessage())

    log = logging.getLogger("langgraph.checkpoint.serde.jsonplus")
    handler = Capture()
    log.addHandler(handler)
    previous = log.level
    log.setLevel(logging.WARNING)
    # `_warn_once` dedupes per type for the life of the process; clear its memo so
    # this test sees the warning whether or not something warmed it earlier.
    import langgraph.checkpoint.serde.jsonplus as jp
    for name in dir(jp):
        if name.startswith("_warned_"):
            try:
                getattr(jp, name).clear()
            except Exception:  # noqa: BLE001
                pass
    try:
        return serde.loads_typed(serde.dumps_typed(payload)), records
    finally:
        log.removeHandler(handler)
        log.setLevel(previous)


def test_the_routing_context_round_trips_with_every_field(routing_context):
    """The whole point of allowlisting it: it must still come back whole."""
    back, _warnings = _warnings_while(
        _serializer(), {"routing_context": routing_context}
    )
    out = back["routing_context"]
    assert isinstance(out, RoutingContext)
    assert out.resolved_filters == {"Year": ["2025"], "Carrier_Group": ["ZURICH GROUP"]}
    assert out.entities.years == ["2025"]
    assert out.query_intent.group_by == ["Product_Line"]
    assert out.output_directives.presentation == "table_only"
    assert out.unresolved_terms[0].term == "notacarrier"
    assert out.analysis_depth == "analytical"


def test_no_unregistered_type_warning_is_logged(routing_context):
    """The reported warning. It names a real future breakage, so it is answered
    by allowlisting the type rather than by silencing the logger."""
    _back, warnings = _warnings_while(
        _serializer(), {"routing_context": routing_context}
    )
    unregistered = [w for w in warnings if "unregistered type" in w]
    assert unregistered == [], unregistered


def test_the_default_serializer_does_warn(routing_context):
    """Guards the test above: if LangGraph stops warning, this fails and tells us
    the allowlist is no longer what is doing the work."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    _back, warnings = _warnings_while(
        JsonPlusSerializer(), {"routing_context": routing_context}
    )
    assert any("unregistered type" in w and "RoutingContext" in w for w in warnings)


def test_the_allowlist_names_the_types_state_actually_holds():
    """`RoutingContext` is the only model on `AgentState`; its nested models are
    encoded inside it rather than as separate extension types."""
    assert _state_types() == (RoutingContext,)


def test_both_checkpointers_use_the_allowlisted_serializer():
    from core.graph import checkpointer as cp

    saver = cp._new_memory_checkpointer()
    allowed = saver.serde._allowed_msgpack_modules
    assert allowed is not True, "a permissive allowlist is what emits the warning"
    assert ("core.schemas.routing", "RoutingContext") in allowed


def test_a_langgraph_without_allowlist_support_still_builds_a_checkpointer(monkeypatch):
    """The saver keeps its own default rather than being handed something it
    cannot use — losing the warning is never worth losing the checkpointer."""
    from core.graph import checkpointer as cp

    monkeypatch.setattr(cp, "_serializer", lambda: None)
    assert cp._new_memory_checkpointer() is not None
