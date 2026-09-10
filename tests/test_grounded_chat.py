"""The chat writer may select evidence; it may not manufacture statements."""
from core.answers.facts import build_fact_pack
from core.answers.grounded import AnswerRequest, compose_answer


def evidence(rows, lens="premium", sql="SELECT premium", **extra):
    return [{"lens": lens, "flow": "gpr", "sql": sql, "rows": rows, **extra}]


def test_facts_bind_value_to_metric_scope_and_source():
    pack = build_fact_pack(evidence([
        {"Carrier": "A", "Premium": 40}, {"Carrier": "B", "Premium": 80}
    ]))
    assert len(pack.facts) == 2
    assert pack.facts[0].id != pack.facts[1].id
    assert dict(pack.facts[0].dimensions)["Carrier"] == "A"
    assert pack.facts[0].value == 40


def test_duplicate_lenses_do_not_discard_facts():
    data = evidence([{"Premium": 1234}], sql="q1") + evidence([{"Premium": 5678}], sql="q2")
    assert {f.value for f in build_fact_pack(data).facts} == {1234, 5678}


def test_selection_cannot_invent_a_number_or_a_carrier():
    request = AnswerRequest("What is A premium?", tuple(evidence([{"Carrier": "A", "Premium": 40}])))
    answer = compose_answer(request, select=lambda candidates: ["Carrier B has 900 million"])
    assert "900" not in answer.text
    assert "Carrier B" not in answer.text
    assert answer.claims
    assert answer.selection_rejected


def test_period_comparison_is_calculated_and_has_input_references():
    request = AnswerRequest("How did premium change?", tuple(evidence([
        {"Carrier": "A", "Year": 2024, "Premium": 100},
        {"Carrier": "A", "Year": 2025, "Premium": 125},
    ])))
    answer = compose_answer(request)
    assert "25%" in answer.text
    claim = next(c for c in answer.claims if c.kind == "change")
    assert len(claim.fact_ids) == 2
    assert claim.formula


def test_zero_prior_does_not_invent_growth_percentage():
    request = AnswerRequest("How did premium change?", tuple(evidence([
        {"Year": 2024, "Premium": 0}, {"Year": 2025, "Premium": 125},
    ])))
    answer = compose_answer(request)
    assert "12500%" not in answer.text
    assert "percentage change is undefined" in answer.text


def test_missing_rows_do_not_turn_into_zero():
    answer = compose_answer(AnswerRequest("What is premium?", tuple(evidence([]))))
    assert not answer.claims
    assert "no usable numeric evidence" in answer.text.lower()


def test_sign_and_percent_units_are_preserved():
    pack = build_fact_pack(evidence([{"Growth_pct": -12, "Score": 19.5}]))
    assert next(f for f in pack.facts if f.metric == "Growth_pct").rendered == "-12%"
    assert next(f for f in pack.facts if f.metric == "Score").rendered == "19.5"


def test_fact_ids_are_stable_when_evidence_order_changes():
    first = evidence([{"Carrier": "A", "Premium": 40}], sql="q1")
    second = evidence([{"Carrier": "B", "Premium": 80}], sql="q2")
    assert {f.id for f in build_fact_pack(first + second).facts} == {f.id for f in build_fact_pack(second + first).facts}


def test_two_lenses_cannot_publish_conflicting_values_for_the_same_metric_and_scope():
    data = evidence([{"Carrier": "A", "Premium": 100}], lens="trend", sql="q1")
    data += evidence([{"Carrier": "A", "Premium": 120}], lens="mix", sql="q2")
    answer = compose_answer(AnswerRequest("premium", tuple(data)))
    assert answer.limitation == "Conflicting evidence"
    assert not answer.claims
    assert "100" not in answer.text and "120" not in answer.text
