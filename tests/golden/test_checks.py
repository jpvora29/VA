"""The quality bar, tested against the failures that were actually reported.

Every check here exists because of a specific complaint: peer names appearing in
answers, the premium missing from a premium reply, charts arriving for some
questions and not others, and numbers that came from the model rather than the
data. These tests are credential-free — that is the point. The live run is gated
on Azure keys, so if the CHECKS were too, the quality bar would only ever be
enforced by hand.
"""
from __future__ import annotations

import pytest

from tests.golden import checks as C
from tests.golden import report as R
from tests.golden.harness import GoldenTrace


@pytest.fixture(autouse=True)
def _vocab(monkeypatch):
    """A known carrier list, so a check's verdict does not depend on the seed DB."""
    monkeypatch.setattr(C, "carrier_vocabulary",
                        lambda: ("Zurich", "AIG", "Chubb", "AXA XL", "Marsh"))


CASE = {"id": "t", "query": "What was Zurich's premium in Singapore in 2024?",
        "category": "lookup", "expected_route": "gpr"}

EVIDENCE = [{"Carrier_Group": "Zurich", "Premium": 12400000},
            {"Carrier_Group": "peer_average", "Premium": 13478261}]


def _trace(**over) -> GoldenTrace:
    base = dict(
        id="t", query=CASE["query"], route="gpr", depth="lookup",
        answer="The book wrote $12.4M with Marsh in 2024, about 8% below the peer average.",
        evidence_rows=list(EVIDENCE), table_rows=list(EVIDENCE),
        token_total=5_000, duration_ms=4_200,
    )
    base.update(over)
    return GoldenTrace(**base)


def _verdict(name, trace, case=CASE):
    return next(r for r in C.run_checks(trace, case) if r.name == name)


# ── confidentiality: the reported bug ────────────────────────────────────────

def test_a_peer_name_in_the_prose_fails():
    v = _verdict("no_named_peer_in_prose", _trace(answer="Zurich trailed AIG on premium."))
    assert not v.passed and "AIG" in v.detail


def test_a_peer_name_in_the_table_fails():
    """The surface a prompt never guarded — the data tab under a chart."""
    rows = [{"Carrier_Group": "Chubb", "Premium": 8_000_000}]
    v = _verdict("no_named_peer_in_table", _trace(table_rows=rows))
    assert not v.passed and "Chubb" in v.detail


def test_a_peer_name_in_a_chart_label_fails():
    specs = [{"type": "bar", "x": "Carrier_Group", "y": ["Premium"], "series": ["AXA XL"]}]
    v = _verdict("no_named_peer_in_chart_labels", _trace(chart_specs=specs))
    assert not v.passed and "AXA XL" in v.detail


def test_the_subject_and_marsh_may_be_named():
    v = _verdict("no_named_peer_in_prose",
                 _trace(answer="Zurich wrote $12.4M with Marsh in 2024."))
    assert v.passed


def test_a_carrier_the_question_named_is_not_a_peer():
    """Ask about two carriers and both may be named."""
    case = {**CASE, "query": "Compare Zurich and AIG premium in Singapore."}
    v = _verdict("no_named_peer_in_prose",
                 _trace(answer="Zurich wrote more than AIG."), case)
    assert v.passed


def test_an_aggregated_answer_passes():
    v = _verdict("no_named_peer_in_prose",
                 _trace(answer="The book sits 8% below the peer average across six peers."))
    assert v.passed


def test_the_check_skips_rather_than_passes_without_a_vocabulary(monkeypatch):
    """A check that cannot look must never report success."""
    monkeypatch.setattr(C, "carrier_vocabulary", lambda: ())
    v = _verdict("no_named_peer_in_prose", _trace(answer="Zurich trailed AIG."))
    assert v.skipped


# ── grounding ────────────────────────────────────────────────────────────────

def test_an_answer_with_no_figure_fails():
    """'It's not showing premium' is this check."""
    v = _verdict("answer_states_a_figure",
                 _trace(answer="The book performed broadly in line with the market."))
    assert not v.passed


def test_an_invented_number_fails():
    v = _verdict("numbers_trace_to_evidence", _trace(answer="The book wrote $99.9M."))
    assert not v.passed and "99.9" in v.detail


def test_a_derived_percentage_passes():
    """A gap computed from two evidence figures is arithmetic, not invention."""
    assert _verdict("numbers_trace_to_evidence", _trace()).passed


def test_a_year_is_not_a_claim():
    v = _verdict("numbers_trace_to_evidence",
                 _trace(answer="In 2024 the book wrote $12.4M."))
    assert v.passed


def test_grounding_skips_when_no_evidence_was_captured():
    assert _verdict("numbers_trace_to_evidence", _trace(evidence_rows=[])).skipped


# ── routing + presentation ───────────────────────────────────────────────────

def test_a_wrong_route_fails():
    v = _verdict("route_as_expected", _trace(route="survey"))
    assert not v.passed and "survey" in v.detail


def test_premium_and_gpr_name_the_same_family():
    """The router says 'premium'; the contract says 'gpr'. Neither is wrong."""
    assert _verdict("route_as_expected", _trace(route="premium")).passed


def test_a_missing_skill_fails():
    case = {**CASE, "expected_skills": ["gpr-share-of-wallet"]}
    v = _verdict("expected_skills_fired", _trace(selected_skills=["gpr-marsh-market"]), case)
    assert not v.passed and "gpr-share-of-wallet" in v.detail


def test_an_errored_turn_fails_as_unanswered():
    v = _verdict("answered", _trace(answer="", error="AuthenticationError: nope"))
    assert not v.passed and "Authentication" in v.detail


def test_a_chart_question_with_no_chart_fails():
    """'Charts are not coming up for some of the questions.'"""
    case = {**CASE, "category": "chart", "query": "Plot Zurich's premium by year."}
    v = _verdict("chart_rendered_when_asked", _trace(chart_specs=[]), case)
    assert not v.passed


def test_a_chart_question_with_a_chart_passes():
    case = {**CASE, "category": "chart"}
    specs = [{"type": "bar", "x": "Year", "y": ["Premium"], "series": []}]
    assert _verdict("chart_rendered_when_asked", _trace(chart_specs=specs), case).passed


def test_a_non_chart_question_is_not_asked_for_one():
    assert _verdict("chart_rendered_when_asked", _trace(chart_specs=[])).skipped


# ── cost ─────────────────────────────────────────────────────────────────────

def test_a_runaway_turn_fails_its_budget():
    v = _verdict("within_token_budget", _trace(token_total=C.TOKEN_BUDGET + 1))
    assert not v.passed


def test_a_slow_turn_fails_its_budget():
    v = _verdict("within_latency_budget", _trace(duration_ms=C.LATENCY_BUDGET_MS + 1))
    assert not v.passed


# ── the scorecard ────────────────────────────────────────────────────────────

def test_the_scorecard_buckets_by_query_and_by_check_category():
    card = R.score([_trace()], [CASE])
    assert "lookup" in card.by_query_category
    assert C.CONFIDENTIALITY in card.by_check_category
    assert card.overall.total > 0


def test_a_bucket_of_pure_skips_is_not_a_perfect_score():
    """The self-flattery a quality tool must never commit."""
    tally = R.Tally(skipped=9)
    assert not tally.scored
    assert "n/a" in R.render(R.score([_trace(answer="", error="boom")], [CASE]))


def test_failures_name_the_case_and_the_rule():
    card = R.score([_trace(answer="Zurich trailed AIG.")], [CASE])
    assert any(cid == "t" and r.name == "no_named_peer_in_prose" for cid, r in card.failures)


def test_the_scorecard_renders_without_traces():
    assert "no failures" in R.render(R.score([], []))


def test_every_check_is_registered_once():
    names = [c.name for c in C.CHECKS]
    assert len(names) == len(set(names))
    assert {c.category for c in C.CHECKS} <= {
        C.CONFIDENTIALITY, C.GROUNDING, C.ROUTING, C.PRESENTATION, C.COST,
    }
