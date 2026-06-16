"""ContextEngine sources valid years from the DATA, not the config lists.

Exercises the `resolve_valid_years` stage in isolation with an injected distinct
registry — the heavy collector/retriever path is covered elsewhere.

Run:  pytest tests/context/test_engine_years.py -q
"""
from __future__ import annotations

from core.context.engine import ContextEngine


class _StubDistinct:
    def __init__(self, years):
        self._years = years
        self.asked_flow = None

    def valid_years(self, flow):
        self.asked_flow = flow
        return self._years


def test_engine_sources_valid_years_from_distinct_registry():
    stub = _StubDistinct(["2023", "2024", "2025"])
    engine = ContextEngine(distinct_registry=stub)
    assert engine.resolve_valid_years("gpr") == ["2023", "2024", "2025"]
    assert stub.asked_flow == "gpr"


def test_engine_valid_years_degrades_on_error():
    class _Boom:
        def valid_years(self, flow):
            raise RuntimeError("db down")

    engine = ContextEngine(distinct_registry=_Boom())
    assert engine.resolve_valid_years("gpr") == []  # never breaks the build
