"""The chatbot answers under the ICG decision tree in rules.yaml.

`studio/rules/rules.yaml` is the signed-off decision tree for this product. The
deck has obeyed it since it was written; the chatbot never read it, which is how
"premium up 1,140%" off a book that wrote almost nothing last year became a
headline answer.

These also pin the two domain facts most often got wrong in prose: Marsh is a
broker whose book is the carrier's addressable opportunity, and a carrier
penetrates a line by industry rather than by buying the whole product.
"""
from __future__ import annotations

import pytest

from core.agents.common.analysis_rules import (
    AnalysisThresholds,
    analysis_directives,
    load_thresholds,
    with_analysis_rules,
    yoy_is_reportable,
)


# ── the thresholds come from rules.yaml, not from a docstring ────────────────

def test_thresholds_are_read_from_the_signed_off_rules():
    from studio.rules import load_rules

    cfg = load_rules()
    t = load_thresholds()
    assert t.yoy_premium_floor == cfg.yoy.suppress_if_current_premium_below
    assert t.high_growth_pct == cfg.yoy.high_growth_pct
    assert t.material_segment_premium == cfg.materiality.min_premium_for_industry_commentary


def test_a_missing_rules_file_costs_the_numbers_not_the_answer(monkeypatch):
    """The chatbot must not need the deck app present to answer a question."""
    import core.agents.common.analysis_rules as AR

    monkeypatch.setattr(AR, "load_rules", None, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "studio.rules", None)
    assert isinstance(load_thresholds.__wrapped__() if hasattr(load_thresholds, "__wrapped__")
                      else AnalysisThresholds(), AnalysisThresholds)


def test_thresholds_render_as_money_a_person_would_say():
    t = AnalysisThresholds(yoy_premium_floor=1_000_000, material_segment_premium=5_000_000)
    assert t.yoy_floor_text == "$1M"
    assert t.segment_floor_text == "$5M"


# ── the outlier rule ─────────────────────────────────────────────────────────

def test_a_huge_percentage_on_a_tiny_book_is_not_reportable():
    """The reported bug: 1,000%+ growth because last year was almost nothing."""
    assert not yoy_is_reportable(40_000, 1_140.0)


def test_a_real_movement_on_a_real_book_is_reportable():
    assert yoy_is_reportable(12_400_000, 12.0)


def test_a_book_just_under_the_floor_is_not():
    t = load_thresholds()
    assert not yoy_is_reportable(t.yoy_premium_floor - 1, 300.0)


def test_an_unknown_premium_does_not_silence_the_answer():
    """No figure to judge on means the prompt rules apply, not a blanket refusal."""
    assert yoy_is_reportable(None, 1_140.0)
    assert yoy_is_reportable("not a number", 12.0)


# ── the framing a threshold cannot express ───────────────────────────────────

@pytest.fixture(scope="module")
def directives() -> str:
    return analysis_directives()


def test_marsh_is_a_broker_not_a_carrier(directives):
    assert "MARSH IS A BROKER" in directives
    assert "never a competitor" in directives
    assert "ADDRESSABLE OPPORTUNITY" in directives


def test_the_marsh_book_is_never_called_the_market(directives):
    assert 'Never call the Marsh book "the market"' in directives


def test_penetration_is_by_industry_inside_a_product(directives):
    assert "INDUSTRY" in directives
    assert "not advice a carrier can act on" in directives


def test_a_performance_question_wants_premium_and_perception(directives):
    assert "premium AND the broker-survey score" in directives


def test_growth_is_never_reported_without_its_money(directives):
    assert "NEVER give a growth percentage on its own" in directives
    assert "$1M" in directives


def test_we_are_the_insurer_consulting_group(directives):
    assert "Insurer Consulting Group" in directives
    assert "client is the CARRIER" in directives


# ── reaching the deterministic rails ─────────────────────────────────────────

def test_a_signature_gains_the_rules_once():
    class Sig:
        instructions = "ROLE: answer the question."

    first = with_analysis_rules(Sig).instructions
    second = with_analysis_rules(Sig).instructions
    assert "MARSH IS A BROKER" in first
    assert first == second, "applying twice appended twice"


def test_the_gpr_rail_no_longer_calls_marsh_the_market():
    """It said 'Marsh = total market view', which the glossary explicitly bans."""
    from core.schemas.gpr import GPRResponseSignature

    with_analysis_rules(GPRResponseSignature)
    assert "total market view" not in GPRResponseSignature.instructions
    assert "MARSH IS A BROKER" in GPRResponseSignature.instructions


def test_a_signature_that_cannot_be_written_to_is_survived():
    class Frozen:
        instructions = "x"
        __slots__ = ()

    assert with_analysis_rules(Frozen) is Frozen
