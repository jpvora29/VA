"""Registry dispatch + the first primitive + DI isolation.

Proves Phase 0's acceptance: the registry is resolvable via DI, one primitive is
green over both flows, unknown names raise (so the orchestrator can fall back),
and a stub primitive can be injected without touching any global.

Run:  pytest tests/analytics -q
"""
from __future__ import annotations

import pytest

from core.analytics import (
    AnalyticsFact,
    AnalyticsRegistry,
    PrimitiveArgs,
    UnknownPrimitiveError,
    build_default_registry,
    build_frame,
)
from tests.analytics.fixtures import GPR_ROWS, SINGLE_YEAR_ROWS, SURVEY_ROWS


def test_default_registry_has_builtin():
    reg = build_default_registry()
    assert "count_distinct_periods" in reg
    assert "count_distinct_periods" in reg.names()


def test_count_distinct_periods_gpr():
    reg = build_default_registry()
    fact = reg.run("count_distinct_periods", build_frame(GPR_ROWS), PrimitiveArgs(flow="gpr"))
    assert isinstance(fact, AnalyticsFact)
    assert fact.value == 2                      # 2023, 2024
    assert fact.dims["column"] == "Year"
    assert fact.support == [{"Year": "2023"}, {"Year": "2024"}]
    assert fact.formula == "COUNT(DISTINCT Year)"


def test_count_distinct_periods_survey():
    reg = build_default_registry()
    fact = reg.run("count_distinct_periods", build_frame(SURVEY_ROWS), PrimitiveArgs(flow="survey"))
    assert fact.value == 2                       # Survey_Year 2023, 2024
    assert fact.dims["column"] == "Survey_Year"


def test_count_distinct_periods_single_year():
    reg = build_default_registry()
    fact = reg.run("count_distinct_periods", build_frame(SINGLE_YEAR_ROWS), PrimitiveArgs(flow="gpr"))
    assert fact.value == 1                        # timeline gating must NOT fire a multi-year view


def test_count_distinct_periods_no_temporal_column():
    reg = build_default_registry()
    fact = reg.run("count_distinct_periods", build_frame([{"Premium": 10}]), PrimitiveArgs(flow="gpr"))
    assert fact.value == 0
    assert fact.support == []


def test_unknown_primitive_raises():
    reg = build_default_registry()
    with pytest.raises(UnknownPrimitiveError):
        reg.get("nope")


def test_dependency_injection_of_stub_primitive():
    """A scoped registry built from an injected map runs the stub — no global touched."""
    def stub(frame, args) -> AnalyticsFact:
        return AnalyticsFact(name="stub", value=42, unit="x")

    reg = AnalyticsRegistry({"stub": stub})
    assert reg.run("stub", build_frame([]), PrimitiveArgs(flow="gpr")).value == 42
    assert "count_distinct_periods" not in reg     # isolation: default builtins absent


def test_args_cache_key_is_hashable_and_stable():
    a = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",), filters={"Country": "Canada"})
    b = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",), filters={"Country": "Canada"})
    assert a.cache_key() == b.cache_key()
    assert len({a.cache_key(), b.cache_key()}) == 1   # usable as a dict/set key
