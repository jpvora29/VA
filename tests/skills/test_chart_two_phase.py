"""Two-phase (select -> detail) chart generation, stubbed (no LLM).

`generate_chart_two_phase` takes the predictors as callables, so the orchestration
— pick type, inject only that type's detail, stamp the decided type, short-circuit
on `none`, fall back to single-phase on selector error — is testable without creds.

Run:  pytest tests/skills/test_chart_two_phase.py -q -o pythonpath=.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.agents.common.chart_spec import (
    CHART_TYPES,
    generate_chart_two_phase,
    sanitize_chart_type,
)


def _type(value):
    return lambda **_kw: SimpleNamespace(chart_type=value)


def _spec(chart_data, sink=None):
    def _predict(**kw):
        if sink is not None:
            sink.update(kw)
        return SimpleNamespace(chart_data=chart_data)

    return _predict


# ── sanitize ────────────────────────────────────────────────────────────────


def test_sanitize_accepts_known_types_case_insensitively():
    for t in CHART_TYPES:
        assert sanitize_chart_type(SimpleNamespace(chart_type=t.upper())) == t
    assert sanitize_chart_type("none") == "none"
    assert sanitize_chart_type(SimpleNamespace(chart_type="not-a-type")) == ""
    assert sanitize_chart_type(SimpleNamespace(chart_type=None)) == ""


# ── orchestration ───────────────────────────────────────────────────────────


def test_only_decided_type_detail_is_injected_and_type_is_stamped():
    sink: dict = {}
    spec = generate_chart_two_phase(
        base_rules="BASE",
        user_query="premium and growth",
        sql_output=[{"Year": 2024, "Premium": 1, "Growth": 2}],
        type_predictor=_type("combo"),
        spec_predictor=_spec({"chart_type": "bar", "x": "Year"}, sink),
        detail_provider=lambda t: f"DETAIL[{t}]",
    )
    # phase one is authoritative for the type...
    assert spec["chart_type"] == "combo"
    # ...and only the combo detail was appended to the base rules.
    assert sink["chart_creation_rules"] == "BASE\n\nDETAIL[combo]"


def test_none_short_circuits_without_calling_spec_predictor():
    called: list[int] = []

    def _guard(**_kw):
        called.append(1)
        return SimpleNamespace(chart_data={})

    out = generate_chart_two_phase(
        base_rules="BASE",
        user_query="just one number",
        sql_output=[{"Total": 5}],
        type_predictor=_type("none"),
        spec_predictor=_guard,
        detail_provider=lambda t: None,
    )
    assert out == {}
    assert not called


def test_selector_error_falls_back_to_single_phase():
    def _boom(**_kw):
        raise RuntimeError("selector down")

    sink: dict = {}
    spec = generate_chart_two_phase(
        base_rules="BASE",
        user_query="trend",
        sql_output=[{"Year": 2023}, {"Year": 2024}],
        type_predictor=_boom,
        spec_predictor=_spec({"chart_type": "line"}, sink),
        detail_provider=lambda t: "SHOULD-NOT-APPEAR",
    )
    # No detail appended, no forced type — the spec predictor decides everything.
    assert sink["chart_creation_rules"] == "BASE"
    assert spec == {"chart_type": "line"}


def test_unknown_type_skips_detail_but_still_generates():
    sink: dict = {}
    spec = generate_chart_two_phase(
        base_rules="BASE",
        user_query="something",
        sql_output=[{"a": 1, "b": 2}],
        type_predictor=_type("weird-type"),  # sanitizes to ""
        spec_predictor=_spec({"chart_type": "bar"}, sink),
        detail_provider=lambda t: f"DETAIL[{t}]",
    )
    assert sink["chart_creation_rules"] == "BASE"  # no detail for unknown
    assert spec == {"chart_type": "bar"}  # not overridden
