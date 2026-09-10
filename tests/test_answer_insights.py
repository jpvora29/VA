"""Carrier-aware growth answers, with depth computed from the same evidence."""
from copy import deepcopy

import pytest

from core.answers.claims import compile_claims
from core.answers.facts import build_fact_pack
from core.answers.grounded import AnswerRequest, compose_answer, render_claims, validate_record


QUESTION = "Show premium growth for Chubb across all product-lines"


def growth_evidence():
    rows = [dict(Product_Line=product, Year=year, Premium=value)
            for product, values in [("Property", (100, 160)), ("Cyber", (80, 100)),
                                    ("Marine", (60, 40)), ("Casualty", (60, 90))]
            for year, value in zip((2024, 2025), values)]
    return ({"flow": "gpr", "lens": "growth", "sql": "recorded grouped result",
             "scope": {"Carrier_Group": "CHUBB", "Country": "Canada"}, "rows": rows},)


def test_growth_headline_names_the_carrier_and_overall_change():
    answer = compose_answer(AnswerRequest(QUESTION, growth_evidence()))
    lead = answer.text.split("\n")[0]
    assert "Chubb's" in lead
    assert "$300" in lead and "$390" in lead and "30%" in lead
    assert "4" in lead and "returned" in lead  # no claim of unproven book coverage
    assert answer.claims[0].kind == "portfolio_change"


def test_growth_includes_drivers_offsets_breadth_and_mix_without_filter_spam():
    answer = compose_answer(AnswerRequest(QUESTION, growth_evidence()))
    assert len(answer.claims) >= 6
    assert {"growth_driver", "growth_offset", "growth_breadth", "premium_mix"} <= {c.kind for c in answer.claims}
    assert "Property" in answer.text and "Marine" in answer.text
    assert "Cyber" in answer.text and "Casualty" in answer.text
    assert "Canada" not in answer.text  # the shared filter is already a pill
    assert answer.text.count("Chubb") == 1
    assert answer.text.count("2024") == answer.text.count("2025") == 1
    assert validate_record(answer.as_dict(), answer.text, growth_evidence())


def test_sparse_model_selection_cannot_reduce_analysis_to_one_generic_line():
    answer = compose_answer(AnswerRequest(QUESTION, growth_evidence()),
                            select=lambda claims: [next(c.id for c in claims if c.kind == "observation")])
    assert answer.claims[0].kind == "portfolio_change"
    assert len(answer.claims) >= 6


def test_lookup_stays_short_and_uses_the_carrier_as_subject():
    evidence = ({"flow": "gpr", "scope": {"Carrier_Group": "CHUBB", "Country": "Canada", "Year": 2025},
                 "rows": [{"Premium": 390}]},)
    answer = compose_answer(AnswerRequest("Chubb premium?", evidence, shape="lookup"))
    assert len(answer.claims) == 1 and "Chubb's" in answer.text
    assert "Canada" not in answer.text and "2025" not in answer.text
    assert validate_record(answer.as_dict(), answer.text, evidence)


def test_old_saved_answer_records_still_verify():
    evidence = growth_evidence()
    facts = build_fact_pack(evidence)
    claim = next(c for c in compile_claims(facts, "") if c.kind == "change")
    used = tuple(f for f in facts.facts if f.id in claim.fact_ids)
    text = render_claims([claim])
    record = {"version": 1, "facts": [f.as_dict() for f in used],
              "claims": [claim.as_dict()], "content": text}
    assert validate_record(record, text, evidence)


def test_missing_product_period_is_not_silently_zero_filled_or_called_complete():
    evidence = deepcopy(growth_evidence())
    evidence[0]["rows"] = evidence[0]["rows"][:-1]
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert "portfolio_change" not in {c.kind for c in answer.claims}
    assert any(c.kind == "growth_coverage" for c in answer.claims)
    assert validate_record(answer.as_dict(), answer.text, evidence)


@pytest.mark.parametrize("metric", ["Score", "Share_pct", "Peer_Avg_Premium"])
def test_scores_rates_and_peer_averages_are_not_summed_as_premium(metric):
    evidence = deepcopy(growth_evidence())
    for row in evidence[0]["rows"]:
        row[metric] = row.pop("Premium")
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert "portfolio_change" not in {c.kind for c in answer.claims}


def test_changed_carrier_or_derived_number_fails_verification():
    evidence = growth_evidence()
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    for changed in (answer.text.replace("Chubb", "Zurich"), answer.text.replace("30%", "90%")):
        record = answer.as_dict()
        record["content"] = changed
        assert not validate_record(record, changed, evidence)


@pytest.mark.parametrize("backend", ["sql", "pandas"])
@pytest.mark.parametrize("primitive", ["compute_yoy", "compute_yoy_to_date"])
def test_growth_tool_operands_reach_the_full_answer_and_provenance(backend, primitive):
    import pandas as pd
    from sqlalchemy import create_engine
    from core.analytics import library
    from core.analytics.frames import frame_source
    from core.analytics.tools.rows import facts_digest, facts_to_rows
    from core.analytics.types import PrimitiveArgs

    rows = [dict(row, Carrier_Group="CHUBB", Country="Canada", Billing_Date=f"{row['Year']}-06-15")
            for row in growth_evidence()[0]["rows"]]
    book = pd.DataFrame(rows)
    engine = create_engine("sqlite://")
    book.to_sql("GPR", engine, index=False)
    source = engine if backend == "sql" else frame_source({"GPR": book})
    args = PrimitiveArgs("gpr", "premium", ("Product_Line",), {"Carrier_Group": "CHUBB", "Country": "Canada"})
    facts = getattr(library, primitive)(args, engine=source)
    evidence = ({"flow": "gpr", "lens": "growth", "scope": dict(args.filters),
                 "rows": facts_to_rows(facts), "facts": facts_digest(facts)},)
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert "$300" in answer.text and "$390" in answer.text and "30%" in answer.text
    assert len(answer.claims) >= 6
    if primitive.endswith("to_date"):
        assert answer.text.count("through Q2 in both years") == 1
    assert validate_record(answer.as_dict(), answer.text, evidence)
    engine.dispose()


def test_comparison_inputs_do_not_guess_a_missing_prior_year_or_measure():
    evidence = ({"flow": "gpr", "rows": [{"YoY_%": 50}], "facts": [{
        "name": "yoy", "column": "YoY_%", "value": 50, "unit": "%", "dims": {"year": 2025},
        "support": [{"yr": 2025, "prev": 100, "measure": 150}]}]},)
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert "$" not in answer.text and "2024" not in answer.text


def test_conflicting_comparison_operands_fail_closed():
    evidence = ({"flow": "gpr", "rows": [{"YoY_%": 90}], "facts": [{
        "name": "yoy", "column": "YoY_%", "value": 90, "unit": "%", "dims": {"year": 2025},
        "support": [{"yr": 2025, "prior_year": 2024, "measure_name": "Premium", "prev": 100, "measure": 150}]}]},)
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert not answer.claims and answer.limitation


def test_varying_countries_remain_identifiable_in_the_answer():
    evidence = ({"flow": "gpr", "scope": {"Carrier_Group": "CHUBB", "Year": 2025},
                 "rows": [{"Country": "Canada", "Premium": 390}, {"Country": "France", "Premium": 700}]},)
    answer = compose_answer(AnswerRequest("Compare Chubb premium by country", evidence))
    assert "Canada" in answer.text and "France" in answer.text
    assert validate_record(answer.as_dict(), answer.text, evidence)


def test_different_lenses_cannot_double_the_product_totals():
    evidence = growth_evidence()
    second = dict(evidence[0], lens="another", sql="another query")
    answer = compose_answer(AnswerRequest(QUESTION, (*evidence, second)))
    assert "$600" not in answer.text and "$780" not in answer.text
    assert sum(c.kind == "portfolio_change" for c in answer.claims) == 1
    assert sum(c.kind == "growth_driver" for c in answer.claims) == 1
    assert validate_record(answer.as_dict(), answer.text, (*evidence, second))


def test_one_period_explains_why_a_growth_breakdown_is_unavailable():
    evidence = growth_evidence()
    evidence[0]["rows"] = [r for r in evidence[0]["rows"] if r["Year"] == 2025]
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert "cannot calculate a full growth breakdown" in answer.text
    assert validate_record(answer.as_dict(), answer.text, evidence)


def test_totals_mixed_with_product_rows_are_not_counted_twice():
    evidence = growth_evidence()
    evidence[0]["rows"] += [{"Product_Line": "Total", "Year": 2024, "Premium": 300},
                            {"Product_Line": "Total", "Year": 2025, "Premium": 390}]
    answer = compose_answer(AnswerRequest(QUESTION, evidence))
    assert "portfolio_change" not in {c.kind for c in answer.claims}
    assert "$600" not in answer.text and "$780" not in answer.text
    assert validate_record(answer.as_dict(), answer.text, evidence)
