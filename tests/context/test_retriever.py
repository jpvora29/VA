"""Hybrid resolver contract (decision #4): fuzzy-first, LLM-rescue.

Proves the cost-shaping rule with injected fakes (no DB / no LLM):
  - a fuzzy hit never touches the semantic resolver;
  - a fuzzy miss escalates to semantic ONLY on a semantic column AND only when
    enabled;
  - a fuzzy miss on a non-semantic column never escalates;
  - a semantic-resolver error degrades to "no match", never raises.

Run:  pytest tests/context/test_retriever.py -q
"""
from __future__ import annotations

from core.context.retriever import EntityResolver, semantic_enabled


def _semantic_cols(*cols):
    names = set(cols)
    return lambda col: col in names


def test_fuzzy_hit_skips_semantic():
    calls = {"semantic": 0}

    def fuzzy(_col, _q):
        return ["SWISS RE"]

    def semantic(_col, _q):
        calls["semantic"] += 1
        return ["should not be used"]

    r = EntityResolver(
        fuzzy=fuzzy, is_semantic=_semantic_cols("Carrier_Group"),
        semantic=semantic, enabled=True,
    )
    rv = r.resolve("Carrier_Group", "Swiss Re premium")
    assert rv.values == ["SWISS RE"]
    assert rv.source == "fuzzy"
    assert calls["semantic"] == 0  # the model was never paid for


def test_semantic_rescue_on_semantic_column_when_enabled():
    def fuzzy(_col, _q):
        return []  # string-distance can't bridge "manufacturing"

    def semantic(_col, _q):
        return ["Manufacture of motor vehicles", "Manufacture of food products"]

    r = EntityResolver(
        fuzzy=fuzzy, is_semantic=_semantic_cols("SIC_Major_Class"),
        semantic=semantic, enabled=True,
    )
    rv = r.resolve("SIC_Major_Class", "manufacturing companies")
    assert rv.source == "semantic"
    assert "Manufacture of motor vehicles" in rv.values


def test_no_rescue_on_non_semantic_column():
    calls = {"semantic": 0}

    def fuzzy(_col, _q):
        return []

    def semantic(_col, _q):
        calls["semantic"] += 1
        return ["nope"]

    r = EntityResolver(
        fuzzy=fuzzy, is_semantic=_semantic_cols("SIC_Major_Class"),
        semantic=semantic, enabled=True,
    )
    rv = r.resolve("Carrier_Group", "manufacturing")  # not a semantic column
    assert rv.values == []
    assert rv.source == "none"
    assert calls["semantic"] == 0


def test_no_rescue_when_disabled():
    calls = {"semantic": 0}

    def semantic(_col, _q):
        calls["semantic"] += 1
        return ["nope"]

    r = EntityResolver(
        fuzzy=lambda c, q: [], is_semantic=_semantic_cols("SIC_Major_Class"),
        semantic=semantic, enabled=False,
    )
    rv = r.resolve("SIC_Major_Class", "manufacturing")
    assert rv.source == "none"
    assert calls["semantic"] == 0


def test_semantic_error_degrades_to_no_match():
    def boom(_col, _q):
        raise RuntimeError("LLM down")

    r = EntityResolver(
        fuzzy=lambda c, q: [], is_semantic=_semantic_cols("SIC_Major_Class"),
        semantic=boom, enabled=True,
    )
    rv = r.resolve("SIC_Major_Class", "manufacturing")
    assert rv.values == []
    assert rv.source == "none"


def test_match_adapter_returns_values_only():
    r = EntityResolver(fuzzy=lambda c, q: ["X"])
    assert r.match("Carrier_Group", "x") == ["X"]


def test_semantic_enabled_flag(monkeypatch):
    monkeypatch.delenv("CONTEXT_ENGINE_SEMANTIC", raising=False)
    assert semantic_enabled() is False
    monkeypatch.setenv("CONTEXT_ENGINE_SEMANTIC", "on")
    assert semantic_enabled() is True
    monkeypatch.setenv("CONTEXT_ENGINE_SEMANTIC", "off")
    assert semantic_enabled() is False
