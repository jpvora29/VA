"""The narration gate drops sentences about a subject or year the evidence lacks."""
from __future__ import annotations

from types import SimpleNamespace

from core.answers.narration import NarrationBrief, subject_check_for, verify_narration
from core.answers.subjects import build_subject_check

VOCAB = ("CHUBB", "AIG", "AIG GROUP", "ZURICH", "DUAL", "Singapore", "Japan", "New Zealand")


def check(*allowed):
    return build_subject_check(VOCAB, allowed)


def test_a_carrier_the_evidence_never_mentions_is_unsupported():
    assert check("CHUBB", "Singapore", "2024").unsupported(
        "AIG premium in Singapore was $1.5M in 2024.") == ["AIG"]


def test_names_in_the_evidence_pass_whatever_their_casing_or_suffix():
    c = check("AIG GROUP", "ZURICH", "Singapore", "2025")
    assert c.unsupported("Zurich trails AIG in Singapore in 2025.") == []


def test_a_year_the_evidence_never_mentions_is_unsupported():
    assert check("CHUBB", "2025").unsupported("Chubb grew in 2023.") == ["2023"]


def test_english_words_and_lowercase_acronyms_are_not_names():
    c = check("CHUBB")
    assert c.unsupported("A dual focus on aig-style growth for Chubb.") == []


def test_a_country_outside_the_scope_is_unsupported():
    assert check("CHUBB", "Singapore").unsupported("Chubb also leads in Japan.") == ["Japan"]


def test_multiword_countries_match_on_their_identifying_word():
    assert check("New Zealand").unsupported("New Zealand grew.") == []


def _brief(facts_dims, claim_text):
    fact = SimpleNamespace(id="f1", metric="Premium", value=1.5e6, rendered="$1.5M",
                           dimensions=facts_dims)
    claim = SimpleNamespace(id="c1", text=claim_text, formula="", kind="value",
                            fact_ids=("f1",))
    return NarrationBrief(question="How is Chubb doing in Singapore?", shape="analyst",
                          ledger=claim_text, claims=(claim,), facts=(fact,))


def test_the_wrong_subject_sentence_is_dropped_from_a_narration():
    brief = _brief((("Carrier_Group", "CHUBB"), ("Country", "Singapore"), ("Year", "2024")),
                   "CHUBB premium in Singapore was $1.5M in 2024.")
    import core.answers.narration as N
    original = N.warehouse_vocabulary
    N.warehouse_vocabulary = lambda: frozenset(VOCAB)
    try:
        result = verify_narration(
            "Chubb wrote $1.5M in Singapore in 2024. AIG premium in Singapore was $1.5M in 2024.",
            brief)
    finally:
        N.warehouse_vocabulary = original
    assert result.accepted
    assert "AIG" not in result.text
    assert "AIG" in result.dropped


def test_subject_check_uses_the_injected_vocabulary():
    brief = _brief((("Carrier_Group", "CHUBB"),), "CHUBB wrote $1.5M.")
    assert subject_check_for(brief, VOCAB).unsupported("ZURICH wrote more.") == ["ZURICH"]
