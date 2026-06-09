"""Step-3 cardinality gate — pure logic (no DB / no LLM).

Proves the token-reduction contract: low-card columns pass through in full;
high-card columns collapse to the query-resolved subset (or a small sample when
nothing resolves).

Run:  pytest tests/context -q
"""
from __future__ import annotations

from core.context.injection import HIGH_CARD_SAMPLE, gate_enabled, gate_valid_values


def _no_match(_col, _query):
    return []


def test_low_card_column_passes_through_full():
    full = {"Country": ["Canada", "US", "Singapore"]}
    gated = gate_valid_values(
        full, "Zurich in Canada", card_caps={"Country": 30}, matcher=_no_match
    )
    assert gated["Country"] == ["Canada", "US", "Singapore"]


def test_high_card_column_collapses_to_resolved_matches():
    full = {"Carrier_Group": [f"Carrier{i}" for i in range(100)]}

    def matcher(col, query):
        assert col == "Carrier_Group"
        return ["Zurich Insurance Group"]

    gated = gate_valid_values(
        full, "Zurich premium", card_caps={"Carrier_Group": 8}, matcher=matcher
    )
    assert gated["Carrier_Group"] == ["Zurich Insurance Group"]


def test_high_card_no_match_falls_back_to_small_sample():
    full = {"Carrier_Group": [f"Carrier{i}" for i in range(100)]}
    gated = gate_valid_values(
        full, "unmatched", card_caps={"Carrier_Group": 8}, matcher=_no_match
    )
    assert gated["Carrier_Group"] == [f"Carrier{i}" for i in range(HIGH_CARD_SAMPLE)]


def test_missing_cap_uses_default_and_none_values_skipped():
    full = {"Big": list(range(50)), "Empty": None}
    gated = gate_valid_values(full, "q", card_caps={}, matcher=_no_match)
    # 50 > DEFAULT_CARD_CAP (30) -> high-card path (sample, since _no_match).
    assert len(gated["Big"]) == HIGH_CARD_SAMPLE
    assert "Empty" not in gated


def test_token_reduction_is_real():
    """The point of the gate: far fewer values reach the prompt."""
    full = {"Carrier_Group": [f"C{i}" for i in range(550)]}
    gated = gate_valid_values(
        full, "q", card_caps={"Carrier_Group": 8}, matcher=lambda c, q: ["Zurich"]
    )
    assert len(gated["Carrier_Group"]) == 1  # was 550


def test_gate_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CONTEXT_ENGINE_VALID_VALUES", raising=False)
    assert gate_enabled() is False
    monkeypatch.setenv("CONTEXT_ENGINE_VALID_VALUES", "on")
    assert gate_enabled() is True
    monkeypatch.setenv("CONTEXT_ENGINE_VALID_VALUES", "shadow")
    assert gate_enabled() is True
    monkeypatch.setenv("CONTEXT_ENGINE_VALID_VALUES", "off")
    assert gate_enabled() is False
