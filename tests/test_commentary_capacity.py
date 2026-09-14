"""How much a column is allowed to write, and what it is told the page shows.

Two defects behind "the overall slide says one thing and ignores the KPIs":

  * the model was asked for ``len(draft)`` bullets — as many as the RULE COMPOSERS had
    produced, after the claim ledger removed whatever an earlier page already said. A
    box authored for three bullets was routinely asked for one, and no prompt could have
    widened it, because capacity was being read off the fallback;
  * a column never knew which figures its own page displays, so it argued from the fact
    pack in the abstract while the page's headline number sat unexplained beside it.

Pure: the templates are real, but there is no LLM and no database here.
"""
from __future__ import annotations

import pytest

from studio.template_fill import commentary as CM
from studio.template_fill import commentary_batch as B
from studio.template_fill.analyze import analyze
from studio.template_fill.binding_map import template_path
from studio.template_fill.rewrites import PendingRewrite


@pytest.fixture(scope="module")
def overall():
    return analyze(template_path("overall"))


# ── capacity comes from the SLIDE, not from the fallback ────────────────────


def test_capacity_is_the_room_the_box_has_not_the_example_the_author_typed(overall):
    """The headline box is the TALLEST prose box in the deck and carried one example line.

    Counting authored paragraphs read that as capacity 1, so the box beside five KPI tiles
    could never explain more than one of them — and no prompt could have widened it,
    because the cap was upstream of the prompt.
    """
    by_topic = {t["topic"]: t["capacity"] for t in CM.prose_targets(overall)}
    assert by_topic["thesis"] == CM._MAX_COLUMN_BULLETS, \
        "a 5-inch box holds more than the one sentence its author typed into it"
    for topic in ("performance", "reflections", "priorities", "key_messages"):
        assert by_topic[topic] >= 3, topic


def test_a_box_too_small_to_hold_bullets_is_not_asked_for_them():
    from studio.template_fill.analyze import Shape

    tiny = Shape(shape_id=1, name="x", kind="text", h=int(0.4 * 914400),
                 font_size_pt=11.0, paragraphs=["one line"])
    assert CM._box_capacity(tiny) == 1


def test_an_unmeasurable_box_falls_back_to_what_the_author_laid_out():
    """No height or no font size is not a licence to guess at four."""
    from studio.template_fill.analyze import Shape

    unmeasured = Shape(shape_id=1, name="x", kind="text",
                       paragraphs=["a", "b"])           # no h, no font size
    assert CM._box_capacity(unmeasured) == 2


def test_a_column_is_asked_for_its_capacity_not_its_draft_length():
    """The defect, stated directly: a one-line fallback must not cap a three-bullet box."""
    pending = PendingRewrite(draft="one surviving line.", node="commentary-performance",
                             topic="performance", subject="Zurich", capacity=3)
    column = B._columns_from([(0, "note:3:10:0", pending)])[0]
    assert column.bullets == 3
    assert column.draft == ("one surviving line.",)


def test_a_pending_with_no_capacity_still_falls_back_to_the_draft():
    """Older callers keep working rather than silently asking for nothing."""
    pending = PendingRewrite(draft="a.\nb.", node="commentary-working", topic="working")
    assert B._columns_from([(0, "note:1:1:0", pending)])[0].bullets == 2


def test_capacity_never_exceeds_what_a_column_can_be_read_at():
    from studio.template_fill.analyze import Shape

    roomy = Shape(shape_id=1, name="x", kind="text", h=int(20 * 914400),
                  font_size_pt=10.0, paragraphs=[f"bullet {i}" for i in range(12)])
    assert CM._box_capacity(roomy) == CM._MAX_COLUMN_BULLETS


def test_an_unauthored_box_is_not_read_as_holding_nothing():
    from studio.template_fill.analyze import Shape

    assert CM._box_capacity(Shape(shape_id=1, name="x", kind="text", paragraphs=[])) >= 1


# ── a one-paragraph box is a paragraph, not a one-item list ─────────────────


def test_a_single_paragraph_box_is_briefed_as_a_paragraph():
    """Forty-five words of one finding leaves the other four tiles unexplained."""
    rules = CM.column_rules("thesis", 1)
    assert "ONE PARAGRAPH" in rules
    assert "three or four sentences" in rules
    assert "ONE BULLET PER LINE" not in rules


def test_a_multi_bullet_box_keeps_the_bullet_contract():
    rules = CM.column_rules("performance", 3)
    assert "ONE BULLET PER LINE" in rules
    assert "ONE PARAGRAPH" not in rules


# ── the page's own KPI tiles reach the brief ────────────────────────────────


def test_the_pages_kpi_captions_are_read_off_the_template(overall):
    slide = next(s for s in overall.slides if s.index == 2)
    kpis = CM._page_kpis(slide)
    assert "Premium written with Marsh across all lines of business" in kpis
    assert "Change in Premium YoY" in kpis
    assert "Carrier’s overall rank" in kpis


def test_a_slide_with_no_tiles_claims_none(overall):
    slide = next(s for s in overall.slides if s.index == 3)
    assert CM._page_kpis(slide) == ()


def test_the_prose_target_carries_its_pages_tiles(overall):
    thesis = next(t for t in CM.prose_targets(overall) if t["topic"] == "thesis")
    assert thesis["page_kpis"], "the headline box must know what is printed beside it"


def test_the_field_block_names_the_tiles_without_repeating_their_values():
    """Named, not valued: the figures live in the evidence, which the verifier checks.

    Printing the numbers here would hand the model a second source to copy from and give
    the verifier nothing to check that copy against.
    """
    column = B.Column(field_id="thesis.0", targets=(B.Target(0, "note:2:34:0"),),
                      topic="thesis", node="commentary-thesis", bullets=1,
                      draft=("draft.",),
                      page_kpis=("Premium written with Marsh", "Change in Premium YoY"))
    block = B._column_block(column, show_draft=False)
    assert "THIS PAGE DISPLAYS" in block
    assert "Premium written with Marsh" in block
    assert "$" not in block


def test_a_column_whose_page_shows_no_tiles_gets_no_such_line():
    column = B.Column(field_id="performance.1", targets=(B.Target(0, "note:3:10:0"),),
                      topic="performance", node="commentary-performance", bullets=3,
                      draft=("draft.",))
    assert "THIS PAGE DISPLAYS" not in B._column_block(column, show_draft=False)


# ── what the numeric check may and may not demand a citation for ────────────
#
# The reported drop reasons were "not getting the year" and "cannot verify the premium
# numbers". They are the same mechanism: every numeric token in a bullet is matched
# against the rendered text of the facts THAT BULLET CITES. Scoping to citations is right
# and catches a figure quoted from the wrong fact — but it was also dropping correct
# sentences for dating themselves, because "2025" is not inside ``carrier.yoy``.


def _pack():
    from studio.template_fill import commentary_evidence as E

    return E.build_pack({
        "subject": "Zurich",
        "scope": {"Product_Line": "Environmental", "Country": "Singapore"},
        "carrier": {"current_year": 2025, "current": 10_000_000, "prior": 12_000_000,
                    "pct": -16.6667, "delta": -2_000_000},
        "marsh": {"current": 100_000_000, "prior": 80_000_000, "pct": 25},
        "sow": {"current": 10, "delta": -5}, "rank": {},
        "peer": {"sow": 18.5, "n_carriers": 3, "benchmark_count": 3},
    })


def _judge(text, cites):
    from studio.template_fill import commentary_verify as V

    return V.check_numbers([V.Judged(text=text, fact_ids=tuple(cites))], _pack()).judged[0]


def test_a_bullet_is_not_dropped_for_dating_itself():
    """The period is the label on the page, not a claim about it."""
    assert _judge("Marsh-placed premium fell 16.7% in 2025.", ("carrier.yoy",)).kept


def test_a_bullet_may_name_the_scope_it_reports_on():
    assert _judge("Environmental premium in Singapore fell 16.7%.", ("carrier.yoy",)).kept


def test_a_figure_whose_fact_is_not_cited_is_still_refused():
    """The allowance is for period and scope ONLY — the real check is untouched.

    Widening it to the whole pack would let the peer average be quoted as the carrier's
    own premium, which is the failure the citation scoping exists to catch.
    """
    judged = _judge("Premium fell 16.7% while Marsh grew 25.0%.", ("carrier.yoy",))
    assert not judged.kept and "25.0%" in judged.reason


def test_the_same_bullet_passes_once_it_cites_both_facts():
    assert _judge("Premium fell 16.7% while Marsh grew 25.0%.",
                  ("carrier.yoy", "marsh.yoy")).kept


def test_the_writer_is_told_the_citation_rule_mechanically():
    """The check is mechanical, so the instruction has to be — 'cite your sources' is not.

    Combining related facts into one point is asked for elsewhere in the same prompt, and
    every extra figure in a bullet is another fact that must be cited or the whole bullet
    goes.
    """
    voice = CM.deck_voice("balanced", "Zurich")
    assert "CITE THE FACT ID BEHIND EVERY FIGURE" in voice
    assert "the whole bullet is dropped" in voice
