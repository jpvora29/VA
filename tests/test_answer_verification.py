"""Phases 6 and 7: the brief the writer gets, and the checks on what comes back.

The figure check in `core.answers.narration` proves every number on the page
appears in the evidence. Everything here is a failure that passes that check:
a real number bound to the wrong subject, a query that quietly widened its own
scope, a decomposition that does not add up, a required investigation that
simply never happened, a cause asserted from co-movement.

Every check is exercised with a PLANTED violation, because a checker that has
never rejected anything is not known to work.
"""
from __future__ import annotations

import pytest

from core.answers import verification as V
from core.answers.claims import AnswerClaim
from core.answers.facts import AnswerFact
from core.answers.grounded import AnswerRequest, compose_answer
from core.answers.narration import build_brief

SCOPE = {"Carrier_Group": "ZURICH GROUP", "Country": "Singapore"}


def fact(id_, metric="premium", value=100.0, unit="Premium", dims=(), rendered=""):
    return AnswerFact(
        id=id_, metric=metric, value=value, unit=unit,
        rendered=rendered or f"{value:,.1f}", dimensions=tuple(dims),
        source_id="src", lens="test",
    )


def claim(id_, text, fact_ids, kind="change"):
    return AnswerClaim(id=id_, text=text, fact_ids=tuple(fact_ids), kind=kind)


def evidence(**overrides):
    from core.analysis.evidence_ledger import build_evidence

    base = dict(flow="gpr", rows=[{"a": 1}], tool="compute_metric",
                parameters={"name": "compute_contribution"}, requested_scope=SCOPE)
    base.update(overrides)
    return build_evidence(**base)


# --------------------------------------------------------------------------- #
# Phase 6 — the brief
# --------------------------------------------------------------------------- #


def test_synthesis_focus_reaches_the_writer():
    """It was computed by the planner and dropped one call short of here."""
    brief = build_brief("q", "analyst", "ledger", (), (),
                        synthesis_focus="lead on the quarterly gap")
    assert brief.as_payload()["lead_with"] == "lead on the quarterly gap"


def test_the_insight_adapter_no_longer_drops_the_focus():
    """Guards the specific wiring bug: accepted as an argument, never passed on."""
    import inspect

    from core.agents.analyst import insight_writer

    source = inspect.getsource(insight_writer.grounded_insight)
    assert "synthesis_focus=synthesis_focus" in source


def test_the_brief_states_what_the_answer_owes_and_which_dataset_serves_it():
    brief = build_brief("q", "analyst", "l", (), (),
                        requirements=("annual_movement", "quarterly_comparison"))
    assert brief.as_payload()["this_answer_should_cover"] == [
        {"requirement": "annual_movement", "from": "gpr"},
        {"requirement": "quarterly_comparison", "from": "gpr"},
    ]


def test_a_hybrid_performance_answer_leads_on_premium_not_survey():
    """The reported failure: a `both`-routed performance question came back written
    almost entirely from the survey half.

    A flat list of requirement keys read as five equal headings, and a survey
    score is far the easier thing to narrate — one number with a direction, no
    decomposition. The brief now states the proportion, from `intents.yaml`'s own
    ordering rather than from anyone's guess.
    """
    from core.analysis import build_contract
    from core.analysis.operation import PERFORMANCE

    contract = build_contract(
        PERFORMANCE, conditions=("comparable_survey_data",),
        allowed_sources=("gpr", "survey"),
    )
    payload = build_brief("q", "analyst", "l", (), (),
                          requirements=contract.keys()).as_payload()

    assert payload["lead_with_dataset"] == "gpr"
    covered = payload["this_answer_should_cover"]
    assert covered[0]["from"] == "gpr", "premium evidence must come first"
    assert [c["requirement"] for c in covered if c["from"] == "survey"] == [
        "survey_movement"
    ], "the survey half is one supporting requirement, not half the answer"


def test_a_perception_question_still_leads_on_the_survey():
    """The rule is proportion from the contract, not a premium preference."""
    from core.analysis import build_contract
    from core.analysis.operation import PERCEPTION

    contract = build_contract(PERCEPTION, allowed_sources=("survey",))
    payload = build_brief("q", "analyst", "l", (), (),
                          requirements=contract.keys()).as_payload()
    assert payload["lead_with_dataset"] == "survey"


def test_the_narrator_is_told_what_the_lead_dataset_governs():
    """A field the prompt never explains is a field the writer ignores."""
    from core.answers import narrator

    source = narrator.__doc__ or ""
    prompt = " ".join(
        str(v) for v in vars(narrator).values() if isinstance(v, str)
    )
    assert "lead_with_dataset" in prompt + source


def test_the_brief_carries_gaps_as_reader_facing_sentences():
    brief = build_brief("q", "analyst", "l", (), (),
                        limitations=("2024 stops at Q2.",))
    assert brief.as_payload()["could_not_be_established"] == ["2024 stops at Q2."]


def test_findings_say_whether_they_were_measured_or_derived():
    """An observation and a comparison must not read as the same kind of thing."""
    claims = (claim("c1", "Premium was 900.", ("f1",), kind="observation"),
              claim("c2", "Premium fell 250.", ("f1", "f2"), kind="change"))
    payload = build_brief("q", "analyst", "l", claims, ()).as_payload()
    assert [f["kind"] for f in payload["verified_findings"]] == ["observation", "change"]


def test_limitations_ride_on_the_answer_without_entering_the_verified_ledger():
    """The ledger must stay fully derivable from re-checkable claims."""
    request = AnswerRequest(
        "How did Zurich do?",
        ({"flow": "gpr", "lens": "t", "sql": "s",
          "rows": [{"Product_Line": "Property", "Year": 2024, "Premium": 1200.0},
                   {"Product_Line": "Property", "Year": 2025, "Premium": 900.0}]},),
        limitations=("Quarterly detail is not available.",),
    )
    answer = compose_answer(request)
    assert answer.limitations == ("Quarterly detail is not available.",)
    assert "Quarterly detail" not in answer.ledger
    assert answer.as_dict()["limitations"] == ["Quarterly detail is not available."]


def test_an_older_record_without_limitations_still_verifies():
    """The new field is additive; `validate_record` reads named keys only."""
    from core.answers.grounded import validate_record

    request = AnswerRequest(
        "How did Zurich do?",
        ({"flow": "gpr", "lens": "t", "sql": "s",
          "rows": [{"Product_Line": "Property", "Year": 2024, "Premium": 1200.0},
                   {"Product_Line": "Property", "Year": 2025, "Premium": 900.0}]},),
    )
    answer = compose_answer(request)
    record = answer.as_dict()
    record.pop("limitations")
    assert validate_record(record, answer.text)


# --------------------------------------------------------------------------- #
# Phase 7 — scope
# --------------------------------------------------------------------------- #


def test_a_query_that_lost_a_filter_is_caught():
    leaked = evidence(actual_scope={"Carrier_Group": "ZURICH GROUP"})
    failures = V.check_scope([leaked])
    assert failures and failures[0].kind == V.WRONG_SCOPE
    assert "Country" in failures[0].detail
    assert failures[0].stage == V.RETRIEVAL


def test_a_query_that_kept_its_filters_passes():
    assert V.check_scope([evidence()]) == []


def test_a_scope_failure_names_the_step_and_the_record_to_repair():
    leaked = evidence(actual_scope={}, step_id="s2_breakdown")
    failure = V.check_scope([leaked])[0]
    assert failure.step_id == "s2_breakdown"
    assert failure.evidence_id
    assert failure.repair == "re-run the step under the requested scope"


# --------------------------------------------------------------------------- #
# Phase 7 — subject and unit binding
# --------------------------------------------------------------------------- #


def test_a_claim_comparing_two_things_at_once_is_rejected():
    """Different product AND different year is not one comparison."""
    facts = (
        fact("f1", dims=(("Product_Line", "Property"), ("Year", "2024"))),
        fact("f2", dims=(("Product_Line", "Cyber"), ("Year", "2025"))),
    )
    failures = V.check_subject_binding([claim("c1", "x", ("f1", "f2"))], facts)
    assert failures and failures[0].kind == V.WRONG_SUBJECT
    assert failures[0].claim_id == "c1"


def test_a_proper_year_on_year_comparison_passes():
    facts = (
        fact("f1", dims=(("Product_Line", "Property"), ("Year", "2024"))),
        fact("f2", dims=(("Product_Line", "Property"), ("Year", "2025"))),
    )
    assert V.check_subject_binding([claim("c1", "x", ("f1", "f2"))], facts) == []


def test_a_single_fact_observation_is_not_a_comparison():
    facts = (fact("f1", dims=(("Product_Line", "Property"),)),)
    assert V.check_subject_binding([claim("c1", "x", ("f1",), "observation")], facts) == []


def test_a_claim_mixing_a_score_and_a_premium_is_rejected():
    """Both numbers are real and both are in the evidence; the sentence is not."""
    facts = (fact("f1", unit="Premium"), fact("f2", metric="score", unit="Score", value=6.5))
    failures = V.check_units([claim("c1", "x", ("f1", "f2"))], facts)
    assert failures and failures[0].kind == V.WRONG_UNIT
    assert failures[0].stage == V.COMPUTATION


def test_matching_units_pass():
    facts = (fact("f1"), fact("f2", value=200.0))
    assert V.check_units([claim("c1", "x", ("f1", "f2"))], facts) == []


# --------------------------------------------------------------------------- #
# Phase 7 — reconciliation and completeness
# --------------------------------------------------------------------------- #


def test_a_decomposition_that_does_not_add_up_is_caught():
    failures = V.check_decomposition([-300.0, -40.0], headline=-250.0, cut="product")
    assert failures and failures[0].kind == V.INCOMPLETE_DECOMPOSITION
    assert "not attributed" in failures[0].detail


def test_a_reconciling_decomposition_passes():
    assert V.check_decomposition([-300.0, -40.0, 90.0], headline=-250.0) == []


def test_a_required_investigation_that_never_ran_is_caught():
    failures = V.check_completeness(
        ("annual_movement", "quarterly_comparison"), ("annual_movement",), ()
    )
    assert failures and failures[0].kind == V.MISSING_INVESTIGATION
    assert "quarterly_comparison" in failures[0].detail
    assert failures[0].stage == V.PLANNING


def test_a_stated_limitation_satisfies_the_completeness_check():
    """A gap the answer admits to is a complete answer about an incomplete book."""
    assert V.check_completeness(
        ("annual_movement", "quarterly_comparison"), ("annual_movement",),
        ("2024 stops at Q2.",),
    ) == []


# --------------------------------------------------------------------------- #
# Phase 7 — causation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("sentence", [
    "Premium fell because of the loss of a major account.",
    "The decline was caused by rate softening.",
    "Weak pricing drove the Property shortfall.",
])
def test_an_unhedged_cause_is_rejected(sentence):
    failures = V.check_causation(sentence)
    assert failures and failures[0].kind == V.UNSUPPORTED_CAUSATION
    assert failures[0].stage == V.PRESENTATION


@pytest.mark.parametrize("sentence", [
    "The decline may be due to rate softening.",
    "This is consistent with rate softening driving the shortfall.",
    "Property's fall appears to have led to the gap.",
])
def test_an_offered_reading_is_allowed(sentence):
    """An analyst must still be able to interpret; only overclaiming is the fault."""
    assert V.check_causation(sentence) == []


def test_a_plain_observation_is_allowed():
    assert V.check_causation("Property fell 300 while Cyber grew 90.") == []


def test_causal_wording_is_allowed_when_the_evidence_supports_it():
    assert V.check_causation(
        "Premium fell because of the loss of a major account.",
        evidence_supports_cause=True,
    ) == []


# --------------------------------------------------------------------------- #
# Phase 7 — the verdict
# --------------------------------------------------------------------------- #


def test_a_clean_answer_passes_every_check():
    facts = (
        fact("f1", dims=(("Product_Line", "Property"), ("Year", "2024"))),
        fact("f2", dims=(("Product_Line", "Property"), ("Year", "2025"))),
    )
    result = V.verify_answer(V.VerificationInput(
        text="Property fell 300 while Cyber grew 90.",
        claims=(claim("c1", "x", ("f1", "f2")),),
        facts=facts,
        evidence=(evidence(),),
        requirements=("annual_movement",),
        satisfied=("annual_movement",),
    ))
    assert result.passed
    assert result.stage == ""


def test_the_earliest_failing_stage_is_the_one_to_repair():
    """Fixing the writer would only make a wrong-scope answer read better."""
    result = V.verify_answer(V.VerificationInput(
        text="Premium fell because of rate softening.",
        evidence=(evidence(actual_scope={}),),
    ))
    assert not result.passed
    assert result.stage == V.RETRIEVAL
    assert {f.kind for f in result.failures} == {V.WRONG_SCOPE, V.UNSUPPORTED_CAUSATION}


def test_every_failure_kind_names_a_repair_and_an_owning_stage():
    for kind in (V.WRONG_SCOPE, V.WRONG_SUBJECT, V.WRONG_UNIT,
                 V.INCOMPLETE_DECOMPOSITION, V.MISSING_INVESTIGATION,
                 V.UNSUPPORTED_CAUSATION):
        failure = V.Failure(kind=kind, detail="d")
        assert failure.stage in V.STAGE_ORDER
        assert failure.repair


def test_the_verification_stages_match_the_evaluation_harness_vocabulary():
    """A failure found in production and one found in evaluation describe alike."""
    from tests.evaluation import stages

    assert V.STAGE_ORDER == stages.ORDER
