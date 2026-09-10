"""The AI-written answer, and the checks that make it safe to show.

The pipeline's contract in one line: the application decides what is true, the
writer decides what is said, and anything the writer says that the application
did not prove is removed before the reader sees it.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.answers.grounded import AnswerRequest, compose_answer, render_claims, validate_record
from core.answers.narration import supported_numbers, unsupported_in
from core.answers.response_pipeline import write_response
from tests.test_answer_insights import QUESTION, growth_evidence


# ── a writer, without a model ────────────────────────────────────────────────


class ScriptedWriter:
    """A narrator that returns fixed prose, and records the brief it was given."""

    def __init__(self, text):
        self.text = text
        self.brief = None

    def __call__(self, brief):
        self.brief = brief
        return self.text


class BrokenWriter:
    def __call__(self, brief):
        raise TimeoutError("the deployment did not answer")


WRITTEN = """Chubb's book grew 30% to $390, and it did so on the back of one line.

### Where the growth came from
- **Property** — up $60, the largest single contributor.
- **Casualty** — added $30 from a $60 base.

### What went the other way
- **Marine** fell to $40, the only line to shrink.
"""


def narrated(text, question=QUESTION, evidence=None):
    writer = ScriptedWriter(text)
    answer = compose_answer(AnswerRequest(question, evidence or growth_evidence()),
                            narrator=writer)
    return answer, writer


# ── the point of the change ──────────────────────────────────────────────────


def test_the_answer_is_the_writers_prose_not_the_claim_ledger():
    answer, _ = narrated(WRITTEN)
    assert answer.narrated and not answer.narration_rejected
    assert answer.text == WRITTEN.strip()
    assert answer.text != answer.ledger
    assert "### Where the growth came from" in answer.text


def test_the_ledger_is_kept_beside_the_prose_and_still_verifies_it():
    answer, _ = narrated(WRITTEN)
    assert answer.ledger == render_claims(answer.claims)
    assert validate_record(answer.as_dict(), answer.text, growth_evidence())


def test_without_a_writer_the_answer_is_exactly_what_it_always_was():
    plain = compose_answer(AnswerRequest(QUESTION, growth_evidence()))
    assert plain.text == plain.ledger and not plain.narrated
    assert plain.text.startswith("Chubb's premium increased")


def test_the_brief_carries_the_findings_the_shape_and_every_quotable_figure():
    _, writer = narrated(WRITTEN)
    payload = writer.brief.as_payload()
    assert writer.brief.shape == "analyst"
    assert len(payload["verified_findings"]) >= 6
    assert all(f["calculation"] for f in payload["verified_findings"][:1])
    # Every product line is quotable, including ones no selected claim names —
    # that per-slice detail is what a claim list cannot carry.
    quoted = {f["value"] for f in payload["figures_you_may_quote"]}
    assert {"$100", "$160", "$60", "$40"} <= quoted
    assert payload["minimum_the_answer_must_convey"].startswith("Chubb's premium increased")


# ── the checks ───────────────────────────────────────────────────────────────


def test_an_invented_figure_is_cut_and_the_rest_of_the_answer_stands():
    answer, _ = narrated(WRITTEN.replace("- **Casualty** — added $30 from a $60 base.",
                                         "- **Casualty** — added $30 at a 47.2% margin."))
    assert "47.2%" not in answer.text
    assert "Casualty" not in answer.text          # the line carrying it went with it
    assert "**Property** — up $60" in answer.text  # its neighbours did not
    assert answer.narrated and "47.2%" in " ".join(answer.dropped_figures)


def test_an_invented_figure_inside_a_paragraph_costs_only_its_sentence():
    written = ("Chubb's book grew 30% to $390. Momentum is running at 4.7 turns of "
               "the prior cycle. The growth is concentrated.")
    answer, _ = narrated(written)
    assert "4.7" not in answer.text
    assert "Chubb's book grew 30% to $390." in answer.text
    assert "The growth is concentrated." in answer.text


def test_prose_that_loses_the_headline_figure_falls_back_to_the_ledger():
    answer, _ = narrated("Growth was broad-based and the book is in good shape.")
    assert not answer.narrated
    assert answer.narration_rejected == "the headline figure was lost"
    assert answer.text == answer.ledger


def test_a_writer_that_fails_never_fails_the_answer():
    answer = compose_answer(AnswerRequest(QUESTION, growth_evidence()), narrator=BrokenWriter())
    assert answer.text == answer.ledger and not answer.narrated
    assert answer.narration_rejected.startswith("writer unavailable")


def test_an_empty_or_wholly_unsupported_draft_falls_back():
    for draft, reason in ((" ", "empty"),
                          ("Premium reached $1,250,000 on a 9.9% margin.",
                           "nothing survived the figure check")):
        answer, _ = narrated(draft)
        assert not answer.narrated and answer.narration_rejected == reason
        assert answer.text == answer.ledger


def test_a_table_row_with_a_bad_number_goes_without_breaking_the_table():
    written = ("Chubb's book grew 30% to $390.\n\n"
               "| Line | Premium |\n| --- | ---: |\n"
               "| Property | $160 |\n| Cyber | $115 |\n| Marine | $40 |\n")
    answer, _ = narrated(written)
    assert "| Property | $160 |" in answer.text and "| Marine | $40 |" in answer.text
    assert "$115" not in answer.text
    assert "| Line | Premium |" in answer.text


def test_a_table_left_with_no_rows_takes_its_header_with_it():
    written = ("Chubb's book grew 30% to $390.\n\n"
               "| Line | Premium |\n| --- | ---: |\n| Cyber | $115 |\n")
    answer, _ = narrated(written)
    assert "|" not in answer.text
    assert answer.text == "Chubb's book grew 30% to $390."


def test_a_heading_whose_group_was_emptied_is_not_left_hanging():
    written = (WRITTEN.replace("- **Marine** fell to $40, the only line to shrink.",
                               "- **Marine** fell 88.8% on the year."))
    answer, _ = narrated(written)
    assert "What went the other way" not in answer.text
    assert "Where the growth came from" in answer.text


def test_years_and_small_ordinals_are_scope_not_claims():
    allowed = supported_numbers((), ())
    assert unsupported_in("Across 2024 and 2025 the top 3 lines held.", allowed) == []
    assert unsupported_in("Premium was $7.4m.", allowed) == ["$7.4m"]


# ── the stored record ────────────────────────────────────────────────────────


def test_editing_a_figure_in_a_narrated_answer_stops_it_verifying():
    answer, _ = narrated(WRITTEN)
    record = answer.as_dict()
    assert validate_record(record, answer.text, growth_evidence())
    tampered = answer.text.replace("$390", "$920")
    assert not validate_record(record, tampered, growth_evidence())


def test_rewriting_the_prose_without_touching_a_number_still_verifies():
    """Prose is the writer's; only the figures are the application's."""
    answer, _ = narrated(WRITTEN)
    record = dict(answer.as_dict())
    reworded = "Chubb grew 30%, reaching $390 on the strength of Property (+$60)."
    record["content"] = reworded
    assert validate_record(record, reworded, growth_evidence())


def test_a_tampered_ledger_is_rejected_even_when_the_prose_is_clean():
    answer, _ = narrated(WRITTEN)
    record = dict(answer.as_dict(), ledger="Chubb's premium was flat.")
    assert not validate_record(record, answer.text, growth_evidence())


def test_records_written_before_narration_still_verify_unchanged():
    plain = compose_answer(AnswerRequest(QUESTION, growth_evidence()))
    record = dict(plain.as_dict(), version=3)
    record.pop("ledger"), record.pop("narrated")
    assert validate_record(record, plain.text, growth_evidence())


# ── the graph adapter, end to end ────────────────────────────────────────────


class ChatClient:
    """One client standing in for both adapters, as the graph passes one."""

    def __init__(self, text=WRITTEN):
        self.text = text

    def bind_tools(self, *args, **kwargs):
        raise RuntimeError("exercise the deterministic claim ranking")

    def invoke(self, messages):
        self.system = messages[0].content
        self.payload = messages[1].content
        return SimpleNamespace(content=self.text)


def response_state(question=QUESTION):
    evidence = list(growth_evidence())
    return {"messages": [SimpleNamespace(content=question)], "question": question,
            "evidence": evidence, "analyst_evidence": deepcopy(evidence),
            "routing_context": {"resolved_filters": {"Carrier_Group": ["CHUBB"],
                                                     "Country": ["Canada"]}}}


def test_a_turn_returns_written_prose_and_a_record_that_verifies():
    state = response_state()
    result = write_response(state, "gpr_response", ("gpr",), client=ChatClient())
    assert result["gpr_response"] == WRITTEN.strip()
    assert validate_record(result["gpr_response_record"], result["gpr_response"], state["evidence"])


def test_the_writer_is_handed_the_shape_contract_this_turn_detected():
    """The shape is a per-turn decision (`core.agents.common.answer_shape`); the
    writer must be told which one, or every answer comes out the same mould."""
    client = ChatClient()
    state = response_state("Why did Chubb's premium move?")
    state["routing_context"]["output_directives"] = {"shape": "driver"}
    write_response(state, "gpr_response", ("gpr",), client=client)
    assert "[SHAPE — DRIVERS" in client.system
    assert "every number you write must be copied from the brief" in client.system
    assert "verified_findings" in client.payload


def test_a_narrated_turn_is_still_badged_verified_in_the_provenance_panel():
    from core.answers.provenance import build
    state = response_state()
    state.update(write_response(state, "gpr_response", ("gpr",), client=ChatClient()))
    provenance = build(state, state["gpr_response"])
    assert provenance.state == "verified" and not provenance.unsupported
    assert len(provenance.claims) >= 6


@pytest.mark.parametrize("shape,expected", [("lookup", False), ("analyst", True)])
def test_a_lookup_skips_the_writer_and_an_analysis_does_not(shape, expected):
    from core.answers.writer import write_answer
    client = ChatClient("Chubb's premium was $390.")
    answer = write_answer(AnswerRequest("Chubb premium?", growth_evidence(), shape=shape),
                          client=client)
    assert hasattr(client, "system") is expected


def test_the_written_answer_is_the_call_that_streams_to_the_live_draft():
    """`core.streaming` forwards only `final_answer`-tagged tokens, so the reader
    sees the answer being written and never the selector's scratch work."""
    from core.answers.narrator import STREAM_TAG, AnswerNarrator
    from core.answers.narration import build_brief

    tagged = {}

    class Configurable(ChatClient):
        def with_config(self, **kwargs):
            tagged.update(kwargs)
            return self

    narrator = AnswerNarrator(Configurable())
    narrator(build_brief(QUESTION, "analyst", "Chubb's premium was $390.", (), ()))
    assert tagged == {"tags": [STREAM_TAG]}


def test_a_numbered_point_is_one_unit_not_two_sentences():
    """"1." reads as a sentence end, so cutting there would leave a bare marker."""
    written = ("Chubb's book grew 30% to $390.\n\n"
               "1. Property added $60.\n2. Cyber ran at 6.6 times cover.\n")
    answer, _ = narrated(written)
    assert "1. Property added $60." in answer.text
    assert "2." not in answer.text and "6.6" not in answer.text


def wide_evidence():
    """More product lines than a ten-claim ledger can possibly cite."""
    rows = [dict(Product_Line=product, Year=year, Premium=value)
            for product, values in [("Property", (100, 160)), ("Cyber", (80, 100)),
                                    ("Marine", (60, 40)), ("Casualty", (60, 90)),
                                    ("Aviation", (55, 71)), ("Energy", (44, 39)),
                                    ("Credit", (33, 47)), ("Motor", (22, 26))]
            for year, value in zip((2024, 2025), values)]
    return ({"flow": "gpr", "lens": "growth", "sql": "recorded grouped result",
             "scope": {"Carrier_Group": "CHUBB", "Country": "Canada"}, "rows": rows},)


def test_a_figure_no_claim_cites_can_still_be_quoted_and_still_verifies():
    """The writer may quote any figure the turn read back, so the record's check
    recomputes that set from the evidence — the cited facts alone are too narrow.

    A ten-claim ledger cannot name everything a turn reads: here the survey
    scores are in the evidence and in nobody's claim, and an answer that brings
    one in is exactly the "context that used to be there" a claim list drops.
    """
    evidence = wide_evidence() + ({
        "flow": "survey", "lens": "survey",
        "scope": {"Carrier_Name": "CHUBB", "Country": "Canada"},
        "rows": [{"Metric": m, "Score": v} for m, v in
                 [("Claims", 72), ("Underwriting", 64), ("Service", 58)]]},)
    plain = compose_answer(AnswerRequest(QUESTION, evidence))
    assert "64" not in {f.rendered for f in plain.facts}   # no claim states it

    written = "Chubb's premium grew 26.21%, and underwriting scores 64 with the brokers."
    answer, _ = narrated(written, evidence=evidence)
    assert answer.narrated and "64" in answer.text
    assert validate_record(answer.as_dict(), answer.text, evidence)


def test_a_figure_in_no_result_at_all_is_still_refused():
    """The widened set is the turn's evidence, not a licence to invent."""
    evidence = wide_evidence()
    answer, _ = narrated("Chubb's premium grew 26.21% against a market that grew 18.3%.",
                         evidence=evidence)
    assert not answer.narrated and "18.3%" in " ".join(answer.dropped_figures)


def test_a_heading_over_a_table_that_empties_goes_with_it():
    """One pruning pass keeps the heading (its table header is still there) and
    then drops the header — the orphan the check exists to prevent."""
    written = ("Chubb's book grew 30% to $390.\n\n"
               "### The lines behind it\n\n"
               "| Line | Premium |\n| --- | ---: |\n| Cyber | $115 |\n")
    answer, _ = narrated(written)
    assert answer.text == "Chubb's book grew 30% to $390."
