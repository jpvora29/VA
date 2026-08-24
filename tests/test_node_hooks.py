"""Tests for the shared NodeHooks contract (Phase 4 hook parity).

One before/after-model contract, two runtime implementations. These cover the
DSPy-rails side: the validator dispatch, `StandardNodeHooks`, the
`with_node_hooks` decorator, and its wiring into `BaseSQLAgentNode` — all
credential-free (no Initialization import, predictor stubbed).

Run:  pytest tests/test_node_hooks.py -q -o pythonpath=.
"""
from __future__ import annotations

import types

import pytest

from core.agents.common.node_hooks import (
    NodeContext,
    StandardNodeHooks,
    run_after_model_validator,
    validate_chart,
    validate_sql,
    with_node_hooks,
)
from core.context.injector import ContextInjector


# ── validators ───────────────────────────────────────────────────────────────


def test_validate_sql_accepts_select_rejects_writes():
    assert validate_sql("SELECT 1") is None
    assert validate_sql("WITH t AS (SELECT 1) SELECT * FROM t") is None
    assert validate_sql("DELETE FROM gpr") is not None
    # Reads the sql off a Prediction-like result too.
    assert validate_sql(types.SimpleNamespace(sql_query="SELECT 1")) is None
    assert validate_sql(types.SimpleNamespace(sql_query="DROP TABLE gpr")) is not None


@pytest.mark.parametrize(
    "spec,ok",
    [
        ({"chart_type": "none"}, True),
        ({"chart_type": "bar", "y": ["premium"], "x": "carrier"}, True),
        ({"chart_type": "scatter", "y": ["premium"]}, True),  # scatter needs no x
        ({"chart_type": "bar", "y": []}, False),  # no measure
        ({"chart_type": "bar", "y": ["premium"]}, False),  # no x
    ],
)
def test_validate_chart(spec, ok):
    assert (validate_chart(spec) is None) is ok


def test_run_after_model_validator_dispatch():
    assert run_after_model_validator("sql", "SELECT 1") is None
    assert run_after_model_validator("sql", "DELETE FROM x") is not None
    # An unregistered kind is a no-op (None).
    assert run_after_model_validator("unknown", "anything") is None
    assert run_after_model_validator(None, "anything") is None


# ── StandardNodeHooks.after_model ─────────────────────────────────────────────


def test_after_model_returns_result_unchanged_and_traces(caplog):
    hooks = StandardNodeHooks()
    sentinel = types.SimpleNamespace(sql_query="DELETE FROM gpr")
    with caplog.at_level("DEBUG"):
        out = hooks.after_model(sentinel, node="gpr_sql_agent", kind="sql")
    assert out is sentinel  # advisory: never rewrites the output
    # The step is traced (structured fields are rendered by the log formatter;
    # the validator outcome itself is covered by the dispatch tests above).
    assert any("node_after_model" in r.getMessage() for r in caplog.records)


def test_after_model_swallows_validator_errors():
    def _boom(_output):
        raise RuntimeError("validator blew up")

    hooks = StandardNodeHooks(validators={"sql": _boom})
    # Must not propagate — the turn proceeds regardless.
    assert hooks.after_model("SELECT 1", node="n", kind="sql") == "SELECT 1"


# ── StandardNodeHooks.before_model (context injection seam) ───────────────────


def test_before_model_noop_without_bundle():
    hooks = StandardNodeHooks()
    ctx = NodeContext(node="router")
    assert hooks.before_model(ctx).view is None


def test_before_model_injects_view_when_bundle_present():
    injector = ContextInjector(view_by_node={"demo": lambda bundle: ("view", bundle)})
    hooks = StandardNodeHooks(injector=injector)
    bundle = object()
    ctx = hooks.before_model(NodeContext(node="demo", bundle=bundle))
    assert ctx.view == ("view", bundle)


def test_before_model_skips_unsupported_node():
    injector = ContextInjector(view_by_node={"demo": lambda b: "v"})
    hooks = StandardNodeHooks(injector=injector)
    ctx = hooks.before_model(NodeContext(node="not_registered", bundle=object()))
    assert ctx.view is None


# ── with_node_hooks decorator ─────────────────────────────────────────────────


class _SpyHooks:
    def __init__(self) -> None:
        self.before = 0
        self.after: list[tuple[str, str | None]] = []

    def before_model(self, ctx: NodeContext) -> NodeContext:
        self.before += 1
        return ctx

    def after_model(self, result, *, node, kind=None):
        self.after.append((node, kind))
        return result


def test_with_node_hooks_wraps_call_and_passes_through():
    spy = _SpyHooks()
    captured = {}

    def predictor(**kwargs):
        captured.update(kwargs)
        return "result"

    hooked = with_node_hooks(predictor, hooks=spy, node="gpr_sql_agent", kind="sql")
    out = hooked(user_query="q", query_plan="p")

    assert out == "result"
    assert captured == {"user_query": "q", "query_plan": "p"}
    assert spy.before == 1
    assert spy.after == [("gpr_sql_agent", "sql")]


def test_bundle_provider_supplies_bundle_to_before_model():
    seen = {}

    class _Hooks(_SpyHooks):
        def before_model(self, ctx):
            seen["bundle"] = ctx.bundle
            return super().before_model(ctx)

    hooked = with_node_hooks(
        lambda **k: "ok", hooks=_Hooks(), node="n", bundle_provider=lambda: "BUNDLE"
    )
    hooked()
    assert seen["bundle"] == "BUNDLE"


# ── rails wiring: BaseSQLAgentNode runs the hooks around generation ───────────


def test_base_sql_agent_runs_hooks_around_predictor():
    from core.agents.common.sql_agent import BaseSQLAgentNode

    spy = _SpyHooks()
    node = BaseSQLAgentNode(
        flow="gpr",
        schema_tables={"GPR": []},
        rules="",
        valid_values={},
        hooks=spy,
    )
    # Stub the predictor so no LLM call happens.
    node.predictor = lambda **kwargs: types.SimpleNamespace(sql_query="SELECT 1")

    sql = node(user_query="Zurich premium", query_plan="plan")
    assert sql == "SELECT 1"
    assert spy.before == 1
    assert spy.after == [("gpr_sql_agent", "sql")]
