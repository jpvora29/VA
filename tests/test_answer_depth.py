"""The depth an answer reaches, and what it is allowed to depend on.

A "how is X performing" question and a "show me X's growth" question are the same
request over the same rows. So are a premium book and a survey book: both have a
strongest slice, a weakest one, and a direction. And a benchmark is only a finding
once it is subtracted from the figure it benchmarks — whichever tool call it
arrived in.
"""
from types import SimpleNamespace

import pytest

from core.answers.grounded import AnswerRequest, compose_answer, validate_record
from core.answers.response_pipeline import write_response
from tests.test_answer_insights import QUESTION, growth_evidence


def kinds(answer):
    return {c.kind for c in answer.claims}


# ── the decomposition follows the evidence, not the wording ──────────────────

PHRASINGS = [
    "How is Chubb performing?",
    "Give me Chubb's performance",
    "How did Chubb do?",
    "Show premium growth for Chubb across all product-lines",
    "What is driving Chubb's numbers?",
]

DECOMPOSITION = {"portfolio_change", "growth_driver", "growth_offset",
                 "growth_breadth", "premium_mix"}


@pytest.mark.parametrize("question", PHRASINGS)
def test_every_phrasing_of_the_same_question_gets_the_same_analysis(question):
    """The old gate was a regex over the question, so "performance" got four bare
    year-on-year lines and "growth" got the whole decomposition."""
    answer = compose_answer(AnswerRequest(question, growth_evidence()))
    assert DECOMPOSITION <= kinds(answer)
    assert answer.text.startswith("Chubb's premium increased")
    assert validate_record(answer.as_dict(), answer.text, growth_evidence())


def test_the_answer_still_leads_with_the_book_not_an_arbitrary_product_line():
    """With no portfolio claim compiled, the highest-priority claim was whichever
    product line happened to sort first — the answer opened on Casualty."""
    answer = compose_answer(AnswerRequest("How is Chubb performing?", growth_evidence()))
    assert answer.claims[0].kind == "portfolio_change"


def test_one_period_of_evidence_still_yields_no_decomposition():
    """Gated on the evidence means gated on the evidence: no second period, no
    breakdown, whatever the question called itself."""
    evidence = growth_evidence()
    evidence[0]["rows"] = [r for r in evidence[0]["rows"] if r["Year"] == 2025]
    answer = compose_answer(AnswerRequest("How is Chubb performing?", evidence))
    assert not (DECOMPOSITION & kinds(answer))


def test_a_reader_who_did_not_ask_about_growth_is_not_told_it_cannot_be_computed():
    """That claim answers a question about movement. It is the one thing here
    still gated on the wording."""
    evidence = growth_evidence()
    evidence[0]["rows"] = [r for r in evidence[0]["rows"] if r["Year"] == 2025]
    asked = compose_answer(AnswerRequest("What drove the change?", evidence))
    unasked = compose_answer(AnswerRequest("What is Chubb's premium?", evidence))
    assert "comparison_coverage" in kinds(asked)
    assert "comparison_coverage" not in kinds(unasked)


# ── a benchmark pairs across tool calls ──────────────────────────────────────


def peer_evidence():
    """What the analytical path actually produces: one result set per call."""
    subject = {"flow": "gpr", "lens": "peer_benchmark",
               "sql": "-- computed: compute_breakdown(Premium)",
               "scope": {"Carrier_Group": "CHUBB", "Country": "Canada", "Year": 2025},
               "rows": [{"Premium": 390}]}
    peer = {"flow": "gpr", "lens": "peer_benchmark",
            "sql": "-- computed: compute_peer_average_total(Premium)",
            "scope": {"Country": "Canada", "Year": 2025},
            "rows": [{"Peer_Avg_Premium": 512}]}
    return subject, peer


def test_a_peer_average_from_its_own_tool_call_still_becomes_a_gap():
    """Two calls, two provenance strings, two source ids — and the old pairing
    keyed on source id, so it only ever worked when both legs shared a row."""
    answer = compose_answer(AnswerRequest("How is Chubb doing against peers?", peer_evidence()))
    assert answer.claims[0].kind == "peer_gap"
    assert "below the peer average of $512 by $122" in answer.text
    assert validate_record(answer.as_dict(), answer.text, peer_evidence())


def test_the_gap_is_read_against_the_total_not_a_product_line():
    """A country-level benchmark sits under the total AND under every product;
    the closest cut wins, so it pairs with the figure it actually benchmarks."""
    subject, peer = peer_evidence()
    by_line = {"flow": "gpr", "lens": "breakdown", "sql": "-- computed: by product",
               "scope": {"Carrier_Group": "CHUBB", "Country": "Canada", "Year": 2025},
               "rows": [{"Product_Line": p, "Premium": v}
                        for p, v in [("Property", 160), ("Cyber", 100), ("Marine", 40),
                                     ("Casualty", 90)]]}
    answer = compose_answer(AnswerRequest("How does Chubb compare?", (subject, peer, by_line)))
    gap = next(c for c in answer.claims if c.kind == "peer_gap")
    assert "$390" in gap.text and "$512" in gap.text


def test_an_ambiguous_benchmark_states_nothing_rather_than_guessing():
    """Two candidate subjects at the same distance is not a comparison."""
    peer = {"flow": "gpr", "lens": "peer", "sql": "-- computed: peer avg",
            "scope": {"Country": "Canada", "Year": 2025}, "rows": [{"Peer_Avg_Premium": 512}]}
    twins = {"flow": "gpr", "lens": "breakdown", "sql": "-- computed: two markets",
             "scope": {"Country": "Canada", "Year": 2025},
             "rows": [{"Client_Segment": s, "Premium": v} for s, v in
                      [("Corporate", 390), ("Middle Market", 250)]]}
    answer = compose_answer(AnswerRequest("How does Chubb compare?", (peer, twins)))
    assert "peer_gap" not in kinds(answer)


def test_a_score_benchmark_is_never_read_against_a_premium():
    subject = {"flow": "gpr", "lens": "x", "sql": "a", "scope": {"Year": 2025},
               "rows": [{"Premium": 390}]}
    peer = {"flow": "survey", "lens": "y", "sql": "b", "scope": {"Year": 2025},
            "rows": [{"Peer_Avg_Score": 64}]}
    answer = compose_answer(AnswerRequest("compare", (subject, peer)))
    assert "peer_gap" not in kinds(answer)


# ── the survey book gets a decomposition of its own ──────────────────────────


def survey_evidence(*years):
    scores = {2025: [("Claims", 72), ("Underwriting", 64), ("Service", 58),
                     ("Appetite", 51), ("Pricing", 55)],
              2024: [("Claims", 69), ("Underwriting", 66), ("Service", 54),
                     ("Appetite", 52), ("Pricing", 50)]}
    return tuple({"flow": "survey", "lens": "survey", "sql": f"-- computed: sections {year}",
                  "scope": {"Carrier": "CHUBB", "SurveyCountry": "Canada",
                            "Survey_Year": year},
                  "rows": [{"Section": s, "Score": v} for s, v in scores[year]]}
                 for year in years)


def test_survey_scores_are_ranked_instead_of_listed_one_by_one():
    answer = compose_answer(AnswerRequest("How is Chubb performing?", survey_evidence(2025)))
    assert "survey_standing" in kinds(answer)
    assert "strongest returned section is Claims at 72" in answer.text
    assert "weakest is Appetite at 51" in answer.text
    assert "spread of 21" in answer.text
    assert validate_record(answer.as_dict(), answer.text, survey_evidence(2025))


def test_a_survey_year_is_recognised_as_a_period_so_scores_can_move():
    """`Survey_Year` is not in the period NAME list, so on survey evidence nothing
    was a period: no time series, no year-on-year claim, and the year split one
    ranking into one per year."""
    answer = compose_answer(AnswerRequest("How is Chubb performing?", survey_evidence(2024, 2025)))
    assert "survey_movement" in kinds(answer) and "change" in kinds(answer)
    assert "3 of the 5 sections returned improved and 2 declined" in answer.text
    # …and the standing claim is stated once, about the latest year, not per year.
    assert len([c for c in answer.claims if c.kind == "survey_standing"]) == 1
    assert "Claims at 72" in answer.text and "Claims at 69" not in answer.text


def test_a_single_score_is_not_a_ranking():
    evidence = ({"flow": "survey", "lens": "survey", "sql": "s",
                 "scope": {"Carrier": "CHUBB", "Survey_Year": 2025},
                 "rows": [{"Section": "Claims", "Score": 72}]},)
    answer = compose_answer(AnswerRequest("survey scores?", evidence))
    assert "survey_standing" not in kinds(answer)


def test_survey_and_premium_findings_share_one_answer():
    evidence = growth_evidence() + survey_evidence(2025)
    answer = compose_answer(AnswerRequest("How is Chubb performing?", evidence))
    assert {"portfolio_change", "survey_standing"} <= kinds(answer)
    assert validate_record(answer.as_dict(), answer.text, evidence)


# ── the period the turn chose for itself ─────────────────────────────────────


class Recorder:
    """Stands in for both model adapters; keeps the brief it was handed."""

    def bind_tools(self, *args, **kwargs):
        raise RuntimeError("exercise the deterministic ranking")

    def invoke(self, messages):
        self.payload = messages[1].content
        return SimpleNamespace(content="")


def test_a_defaulted_period_reaches_the_writer_so_the_answer_can_say_it():
    """The rails write the chosen year back into the plan for the writer to read,
    and the grounded writer does not read the plan — so it rode in the evidence."""
    client = Recorder()
    state = {"messages": [SimpleNamespace(content=QUESTION)],
             "analyst_evidence": [dict(growth_evidence()[0], defaulted_year=2025)],
             "routing_context": {"resolved_filters": {"Carrier_Group": ["CHUBB"]}}}
    write_response(state, "gpr_response", ("gpr",), client=client)
    assert '"period_chosen_because_the_question_named_none": "2025"' in client.payload


def test_a_period_the_reader_named_is_not_reported_as_chosen_for_them():
    client = Recorder()
    state = {"messages": [SimpleNamespace(content="Chubb premium in 2025")],
             "analyst_evidence": list(growth_evidence()),
             "routing_context": {"resolved_filters": {"Carrier_Group": ["CHUBB"]}}}
    write_response(state, "gpr_response", ("gpr",), client=client)
    assert '"period_chosen_because_the_question_named_none": ""' in client.payload


def test_two_result_sets_that_defaulted_differently_claim_nothing():
    from core.answers.scope import defaulted_period

    assert defaulted_period([{"defaulted_year": 2025}, {"defaulted_year": 2025}]) == "2025"
    assert defaulted_period([{"defaulted_year": 2025}, {"defaulted_year": 2024}]) == ""
    assert defaulted_period([{"defaulted_year": None}, {}]) == ""


# ── one answer, three books ──────────────────────────────────────────────────


def all_three_books():
    from tests.test_answer_depth import peer_evidence, survey_evidence
    return growth_evidence() + survey_evidence(2024, 2025) + peer_evidence()


def test_a_broad_question_says_something_from_every_book_it_read():
    """Ten claims and three books: at its old rank the peer comparison was pushed
    out by a seventh growth sentence — one more cut of the same book instead of
    the number that says whether any of it is good."""
    evidence = all_three_books()
    answer = compose_answer(AnswerRequest("How is Chubb performing?", evidence))
    assert {"portfolio_change", "peer_gap", "survey_standing"} <= kinds(answer)
    assert answer.claims[0].kind == "portfolio_change"     # the book still leads
    assert validate_record(answer.as_dict(), answer.text, evidence)


def test_a_benchmarks_missing_carrier_does_not_make_every_line_repeat_it():
    """A peer average is deliberately not filtered to one carrier. Counting its
    dimensions made the carrier "not shared", so every other sentence started
    spelling it out in an answer that is about that carrier throughout."""
    evidence = all_three_books()
    answer = compose_answer(AnswerRequest("How is Chubb performing?", evidence))
    assert answer.text.count("CHUBB") == 0
    assert answer.text.count("Chubb") == 1                 # the lead names it, once


def test_a_survey_finding_carries_its_period_rather_than_losing_it():
    """The standing sentence says only where a carrier sits; strip the period from
    its suffix and it is a finding with no date on it."""
    answer = compose_answer(AnswerRequest("How is Chubb performing?", all_three_books()))
    standing = next(c for c in answer.claims if c.kind == "survey_standing")
    assert "2025" in standing.text
    # …and it is stated once, not once in the sentence and again in a suffix.
    assert standing.text.count("2025") == 1
