"""The shared narrative contract — both engines produce it, QA consumes it.

The point of the contract is not that it exists but that two differently-built commentary
engines answer the same questions about a slide, so these tests assert on BOTH producers
and on the checks that read the result.
"""
from __future__ import annotations

import pytest

from studio.narrative import ACTION_VERBS, Confidence, SlideNarrative
from studio.posture import Posture


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")


# ── the contract itself ──────────────────────────────────────────────────────


def test_sentences_read_in_the_order_of_the_argument():
    n = SlideNarrative(
        slide_role="portfolio thesis", primary_claim="Premium grew 28.6%.",
        interpretation="That is ahead of the book.", management_implication="Relevance lags.",
        recommended_action="Scale this book.", open_question="Appetite is unconfirmed.")
    assert n.sentences() == ("Premium grew 28.6%.", "That is ahead of the book.",
                             "Relevance lags.", "Scale this book.",
                             "Appetite is unconfirmed.")


def test_a_narrative_carries_only_what_it_has():
    n = SlideNarrative(slide_role="r", primary_claim="One claim.")
    assert n.sentences() == ("One claim.",)


def test_the_action_verb_comes_from_the_closed_vocabulary():
    assert SlideNarrative("r", "c", recommended_action="Defend Cyber.").action_verb == "Defend"
    assert SlideNarrative("r", "c", recommended_action="Grow the book.").action_verb == ""


def test_every_posture_is_an_allowed_action_verb():
    """The posture vocabulary and the contract's verbs must not drift apart."""
    assert all(p.value in ACTION_VERBS for p in Posture)


# ── gaps: what QA is meant to see ────────────────────────────────────────────


def test_a_recommendation_that_says_nothing_specific_is_a_gap():
    n = SlideNarrative("r", "c", ("f1",), recommended_action="Focus on growth.")
    assert "recommended_action_verb" in n.gaps()


def test_an_unvalidated_claim_without_an_open_question_is_a_gap():
    n = SlideNarrative("r", "c", ("f1",), recommended_action="Validate Marine.",
                       confidence=Confidence.UNVALIDATED)
    assert "open_question" in n.gaps()
    named = SlideNarrative("r", "c", ("f1",), recommended_action="Validate Marine.",
                           confidence=Confidence.UNVALIDATED,
                           open_question="Appetite and capacity are unconfirmed.")
    assert named.is_complete()


def test_traceability_is_not_a_per_narrative_gap():
    """Only one engine carries an EvidencePack to cite. Whether missing ids matter is a
    question about the DECK, so it lives in QA (see the traceability tests below), not in
    a rule that would fire on every page of the other engine."""
    assert SlideNarrative("r", "c", recommended_action="Scale it.").gaps() == ()


# ── producer 1: the template-fill engine ─────────────────────────────────────


_FACTS = {
    "subject": "Zurich",
    "carrier": {"current": 44e6, "pct": 97.3, "delta": 22e6},
    "marsh": {"current": 300e6, "pct": 13.5},
    "sow": {"current": 14.7, "delta": 6.2},
    "rank": {"current": 1, "delta": 5, "of_n": 12},
    "peer": {"sow": 11.5},
}


def test_the_template_fill_engine_produces_a_narrative():
    from studio.template_fill.stance import narrative_for

    n = narrative_for(_FACTS, "thesis", name="Cyber", fact_ids=("f1",))
    assert n.slide_role == "portfolio thesis"
    assert n.primary_claim and n.posture is Posture.DEFEND
    assert n.action_verb == "Defend"
    assert n.is_complete()


def test_an_opportunity_page_declares_itself_unvalidated_and_says_why():
    """Premium evidence reaches an observation and no further."""
    from studio.template_fill.stance import narrative_for

    n = narrative_for(_FACTS, "growth", name="Cyber", fact_ids=("f1",))
    assert n.confidence is Confidence.UNVALIDATED
    assert "appetite and capacity" in n.open_question.lower()
    assert n.is_complete()


def test_facts_that_carry_no_claim_produce_no_narrative():
    from studio.template_fill.stance import narrative_for

    assert narrative_for({}, "thesis") is None


# ── producer 2: the QBR pipeline engine ──────────────────────────────────────


def _slide(*sentences):
    from studio.commentary.agent import SlideCommentary
    from studio.commentary.verify import CommentarySentence

    return SlideCommentary(0, "trading_summary",
                           tuple(CommentarySentence(t, ids) for t, ids in sentences))


def test_the_pipeline_engine_produces_the_same_contract():
    n = _slide(("Premium grew 28.6% to $208M.", ("f1", "f2")),
               ("That keeps it at #5 of 12.", ("f3",)),
               ("Validate Renewable Energy: $184.9M sits elsewhere.", ("f4",))).to_narrative()
    assert n.slide_role == "trading summary"
    assert n.primary_claim == "Premium grew 28.6% to $208M."
    assert n.action_verb == "Validate"
    assert n.evidence_fact_ids == ("f1", "f2", "f3", "f4")


def test_the_recommendation_is_not_counted_twice_as_a_claim():
    n = _slide(("Premium grew 28.6% to $208M.", ("f1",)),
               ("Defend Cyber now.", ("f2",))).to_narrative()
    assert n.recommended_action == "Defend Cyber now."
    assert "Defend" not in n.primary_claim


def test_a_slide_the_verifier_emptied_has_no_narrative():
    """Its data gap is the honest answer; inventing a claim would defeat the gap."""
    from studio.commentary.agent import SlideCommentary

    assert SlideCommentary(1, "growth", data_gap="no citable facts").to_narrative() is None


# ── consumer: QA ─────────────────────────────────────────────────────────────


def test_qa_reports_contract_gaps_and_duplicated_slide_roles():
    from studio.template_fill.commentary_qa import check_narratives

    issues = check_narratives([
        SlideNarrative("portfolio thesis", "X grew.", ("f1",), recommended_action="Scale X."),
        SlideNarrative("portfolio thesis", "Y grew.", ("f2",), recommended_action="Grow it."),
    ])
    codes = {i.code for i in issues}
    assert "narrative_missing_recommended_action_verb" in codes
    assert "duplicate_slide_role" in codes


def test_qa_passes_a_well_formed_set():
    from studio.template_fill.commentary_qa import check_narratives

    assert not check_narratives([
        SlideNarrative("portfolio thesis", "X grew.", ("f1",), recommended_action="Scale X."),
        SlideNarrative("management agenda", "Y lags.", ("f2",), recommended_action="Fix Y."),
    ])


def test_qa_ignores_slides_that_have_no_narrative():
    from studio.template_fill.commentary_qa import check_narratives

    assert not check_narratives([None, None])


# ── traceability is asked only where a producer can supply it ────────────────


def test_fact_ids_are_not_demanded_of_an_engine_that_has_none():
    """The template-fill composers ground claims in FIGURES, with no id registry behind
    them. Reporting that on every page would be noise, not a finding."""
    from studio.template_fill.commentary_qa import check_narratives

    assert not check_narratives([
        SlideNarrative("portfolio thesis", "X grew 10%.", recommended_action="Scale X."),
        SlideNarrative("management agenda", "Y lags.", recommended_action="Fix Y."),
    ])


def test_fact_ids_are_demanded_once_some_page_proves_they_exist():
    """A deck whose other pages cite ids has an uncited page worth flagging."""
    from studio.template_fill.commentary_qa import check_narratives

    issues = check_narratives([
        SlideNarrative("portfolio thesis", "X grew.", ("f1",), recommended_action="Scale X."),
        SlideNarrative("management agenda", "Y lags.", (), recommended_action="Fix Y."),
    ])
    assert [i.code for i in issues] == ["narrative_untraceable"]


# ── a page's narrative comes from its composed lines ─────────────────────────


def test_a_prose_column_topic_still_produces_a_narrative():
    """Regression: "performance" is a COLUMN topic, not a composer kind, so building the
    narrative from feedback.points alone silently lost that page."""
    from studio.template_fill.stance import narrative_for

    assert narrative_for(_FACTS, "performance") is None       # no composer of that name
    from_lines = narrative_for(_FACTS, "performance",
                               said=["Premium grew 97.3%.", "Rank improved."], name="Cyber")
    assert from_lines is not None
    assert from_lines.slide_role == "performance assessment"
    assert from_lines.primary_claim == "Premium grew 97.3%."


def test_assembly_collects_one_narrative_per_prose_page(tmp_path):
    """End to end on the real overall template: each prose-bearing page contributes one
    narrative, and the deck's set is contract-clean."""
    from studio.compute import compute_overall
    from studio.template_fill import assemble as A
    from studio.template_fill.binding_map import available
    from studio.template_fill.commentary_qa import check_narratives
    from studio.template_fill.ledger import ClaimLedger

    if "overall" not in set(available()):
        pytest.skip("split templates not present")

    result = compute_overall(
        filters={"Carrier_Group": "Zurich", "Country": "Singapore", "Year": 2025})
    collected: list = []
    A._build_subdeck("overall", result, {}, "overall",
                     providers=A._premium_providers(ClaimLedger(), collected))

    assert len(collected) >= 2, "the overall block has more than one prose page"
    roles = [n.slide_role for n in collected]
    assert "portfolio thesis" in roles
    assert len(roles) == len(set(roles)), f"two pages doing the same job: {roles}"
    assert not check_narratives(collected)
