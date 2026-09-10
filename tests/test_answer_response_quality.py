"""Regressions at the graph adapters, including split and partially scoped results."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.answers.grounded import AnswerRequest, compose_answer, validate_record
from core.answers.response_pipeline import write_response
from tests.test_answer_insights import QUESTION, growth_evidence


class OfflineSelection:
    def bind_tools(self, *args, **kwargs):
        raise RuntimeError("Exercise the deterministic selection fallback")


def split_growth():
    item = growth_evidence()[0]
    return tuple(dict(item, sql=f"grouped premium for {year}",
                      scope=dict(item["scope"], Year=year),
                      rows=[r for r in item["rows"] if r["Year"] == year])
                 for year in (2024, 2025))


def mixed_scope():
    return (
        {"flow": "gpr", "scope": {"Carrier_Group": "ZURICH", "Country": "Canada", "Year": 2025},
         "rows": [{"Product_Line": p, "Premium": v}
                  for p, v in (("Property", 160), ("Cyber", 100), ("Marine", 40))]},
        {"flow": "survey", "scope": {"Carrier_Name": "ZURICH"}, "rows": [{"NPS": 25}]},
    )


def response_state(evidence, question=QUESTION):
    return {"messages": [SimpleNamespace(content=question)], "question": question,
            "route": "both", "evidence": list(evidence), "analyst_evidence": list(evidence),
            "routing_context": {"resolved_filters": {
                "Carrier_Group": ["ZURICH"], "Country": ["Canada"], "Year": ["2025"]}}}


@pytest.mark.parametrize("path", ["response", "analyst"])
def test_shared_pills_suppress_filters_even_when_one_result_has_partial_scope(path, monkeypatch):
    state = response_state(mixed_scope(), "Summarize premium and NPS")
    if path == "response":
        result = write_response(state, "answer", ("gpr", "survey"), client=OfflineSelection())
    else:
        import core.llm
        from core.graph.analyst_subgraph import writer_node
        monkeypatch.setattr(core.llm, "tier_client", lambda *args, **kwargs: OfflineSelection())
        result = writer_node(state)
    answer = result["answer"]
    assert "Canada" not in answer and "2025" not in answer
    assert answer.count("Zurich") == 1
    assert "Marsh-placed" not in answer
    assert validate_record(result["answer_record"], answer, state["evidence"])


@pytest.mark.parametrize("packaging", [growth_evidence, split_growth])
def test_growth_answer_has_carrier_headline_and_explanatory_depth(packaging):
    evidence = packaging()
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert answer.text.startswith("Chubb's premium increased")
    assert "Marsh-placed" not in answer.text
    assert "$300" in answer.text.split("\n")[0] and "$390" in answer.text.split("\n")[0]
    assert len(answer.claims) >= 8
    assert {"growth_driver", "growth_offset", "growth_breadth", "premium_mix", "growth_resilience"} <= {c.kind for c in answer.claims}
    assert "Excluding Property" in answer.text
    assert "Cyber" in answer.text and "Casualty" in answer.text
    assert validate_record(answer.as_dict(), answer.text, evidence)


def test_duplicate_result_does_not_inflate_or_remove_growth_insights():
    evidence = split_growth()
    expected = compose_answer(AnswerRequest(QUESTION, evidence))
    duplicate = dict(evidence[0], sql="repeat of the first result")
    actual = compose_answer(AnswerRequest(QUESTION, (*evidence, duplicate)))
    assert actual.text == expected.text
    assert validate_record(actual.as_dict(), actual.text, (*evidence, duplicate))


def test_different_scopes_and_lenses_are_not_combined_into_growth():
    evidence = deepcopy(split_growth())
    evidence[1]["scope"]["Country"] = "France"
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert not any(c.kind == "portfolio_change" for c in answer.claims)
    evidence = deepcopy(split_growth())
    evidence[1]["lens"] = "different population"
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert not any(c.kind == "portfolio_change" for c in answer.claims)


def test_country_comparison_keeps_both_names_despite_a_selected_country():
    evidence = mixed_scope()
    evidence[0]["rows"].append({"Country": "France", "Product_Line": "Property", "Premium": 999})
    state = response_state(evidence, "Compare premium by country")
    result = write_response(state, "answer", ("gpr", "survey"), client=OfflineSelection())
    assert "Canada" in result["answer"] and "France" in result["answer"]


def test_previous_version_record_still_verifies_without_rewriting_it():
    saved = json.loads((Path(__file__).parent / "fixtures/answers/v2_growth.json").read_text(encoding="utf-8"))
    assert validate_record(saved["record"], saved["record"]["content"], saved["evidence"])


def test_separate_sql_tool_calls_reach_the_answer_and_calculation_drawer():
    from core.answers.provenance import build
    from tests.e2e.chat_server import fixture_engine, fixture_turn, split_tool_evidence
    engine = fixture_engine()
    try:
        turn, _, _ = fixture_turn(QUESTION)
        turn["analyst_evidence"] = split_tool_evidence(engine)
        turn.update(write_response(turn, "gpr_response", ("gpr",), client=OfflineSelection()))
        answer = turn["gpr_response"]
        provenance = build(turn, answer)
        assert answer.startswith("Chubb's premium increased") and "30%" in answer.split("\n")[0]
        assert len(provenance.claims) >= 8
        assert provenance.state == "verified"
        assert not provenance.unsupported
        assert any("Marsh" in term.definition for term in provenance.terms)
        saved = json.loads(json.dumps(turn["gpr_response_record"]))
        assert validate_record(saved, answer, turn["analyst_evidence"])
    finally:
        engine.dispose()


@pytest.mark.parametrize("metric", ["Premium", "Marsh_Premium", "Marsh_Placed_Premium"])
def test_subject_premium_labels_do_not_reintroduce_broker_prefix(metric):
    evidence = ({"flow": "gpr", "scope": {"Carrier_Group": "CHUBB"}, "rows": [{metric: 123}]},)
    assert compose_answer(AnswerRequest("Chubb premium?", evidence)).text == "Chubb's premium was $123."
