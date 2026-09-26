"""The QBR writer's playbook: skills chosen by the facts, and the facts that feed them.

Covers the commentary asks: ICG context in every brief, a decline explained by the line it
came from (with its survey score on the survey basis, and the Marsh market beside it),
growth set against the market, multi-country pages compared, and a human voice.
"""
from __future__ import annotations

from studio.template_fill import commentary_evidence as E
from studio.template_fill import commentary_skills as S
from studio.template_fill import facts_driver as D
from studio.template_fill import facts_survey_lines as SL

DECLINE = {
    "subject": "Zurich",
    "carrier": {"current": 95e6, "prior": 100e6, "delta": -5e6, "pct": -5.0},
    "movers": [{"name": "Casualty", "delta": -4.2e6, "pct": -12.0},
               {"name": "Property", "delta": -1.5e6, "pct": -4.0},
               {"name": "Cyber", "delta": 0.7e6, "pct": 9.0}],
    "pool": [{"name": "Casualty", "delta": 3.0e6}],
    "mover_dim": "line",
    "survey_lines": [{"practice": "Casualty", "line": "casualty", "score": 3.62, "prior": 3.91,
                      "delta": -0.29, "year": 2025, "prior_year": 2024, "country": "Singapore"}],
}
GROWTH = {**DECLINE, "carrier": {"current": 110e6, "prior": 100e6, "delta": 10e6, "pct": 10.0},
          "movers": [{"name": "Cyber", "delta": 7e6}, {"name": "Marine", "delta": 3e6}],
          "survey_lines": [], "pool": []}


def _names(skills):
    return [s.name for s in skills]


# ── the library and its selection ────────────────────────────────────────────


def test_every_skill_on_disk_declares_a_known_condition():
    library = S.library()
    assert {"qbr-icg-context", "qbr-expert-voice", "qbr-decline-diagnosis", "qbr-growth-story",
            "qbr-multi-market", "qbr-survey-link", "qbr-opportunity"} <= set(_names(library))
    assert all(s.applies_when in S.CONDITIONS for s in library)
    assert all(s.body and s.description for s in library)


def test_the_icg_context_and_voice_are_in_every_brief():
    chosen = _names(S.select({}, ()))
    assert chosen[:2] == ["qbr-icg-context", "qbr-expert-voice"]


def test_a_decline_is_briefed_as_a_decline_and_growth_as_growth():
    down = _names(S.select(DECLINE, ()))
    up = _names(S.select(GROWTH, ()))
    assert "qbr-decline-diagnosis" in down and "qbr-growth-story" not in down
    assert "qbr-growth-story" in up and "qbr-decline-diagnosis" not in up


def test_survey_and_opportunity_skills_need_facts_the_writer_can_cite():
    assert "qbr-survey-link" not in _names(S.select(DECLINE, ("carrier.delta",)))
    ids = ("survey.line.casualty", "peer.gap")
    chosen = _names(S.select(DECLINE, ids))
    assert "qbr-survey-link" in chosen and "qbr-opportunity" in chosen


def test_multi_country_pages_get_the_market_comparison_skill():
    two = {**GROWTH, "markets": [{"name": "Singapore"}, {"name": "Japan"}]}
    assert "qbr-multi-market" in _names(S.select(two, ()))
    assert "qbr-multi-market" not in _names(S.select(GROWTH, ()))


def test_the_playbook_says_what_icg_is():
    text = S.playbook(DECLINE, ())
    assert "Insurer Consulting Group" in text and "PLAYBOOK" in text
    assert "qbr-decline-diagnosis" in text


# ── the facts the skills lean on ─────────────────────────────────────────────


def test_the_driver_fact_names_the_line_and_its_share_of_the_fall():
    pack = E.build_pack(DECLINE)
    fact = pack.get("driver.decline") if hasattr(pack, "get") else next(
        i for i in pack.items if i.fact_id == "driver.decline")
    assert fact.entity == "Casualty"
    assert "Casualty accounts for" in fact.rendered and "(84% of it)" in fact.rendered


def test_a_line_that_fell_more_than_the_total_is_said_so():
    facts = {**DECLINE, "carrier": {"current": 98e6, "prior": 100e6}}
    rendered = next(i for i in E.build_pack(facts).items if i.fact_id == "driver.decline").rendered
    assert "more than the carrier's whole" in rendered


def test_survey_scores_become_citable_facts_named_by_line():
    items = {i.fact_id: i for i in E.build_pack(DECLINE).items}
    fact = items["survey.line.casualty"]
    assert fact.rendered == "3.62 in 2025, down 0.29 from 2024"
    assert fact.term == "survey_score"


def test_a_survey_practice_is_paired_with_its_premium_line():
    assert SL.line_for("FINPRO") == "financial lines"
    assert SL.line_for("Cyber") == "cyber"


def test_survey_lines_are_only_read_for_one_market_on_the_survey_basis():
    class Result:
        data_basis = "premium"

    assert SL.load(Result(), {"Country": "Singapore"}) == []
    Result.data_basis = "premium_survey"
    assert SL.load(Result(), {"Country": ["Singapore", "Japan"]}) == []


# ── the rules-based wording names the cause too ──────────────────────────────


def test_the_fallback_decline_line_names_the_line_the_market_and_the_survey():
    line = D.decline_line(DECLINE)
    assert line.startswith("Casualty is where most of the fall came from")
    assert "while Marsh's own Casualty placements grew" in line
    assert "The carrier survey points the same way: Casualty scored 3.62, down 0.29" in line


def test_a_score_that_fell_in_a_line_that_grew_reads_differently():
    """Seen on the seed deck: Cyber grew while its survey score slipped, and the draft
    said the survey 'points the same way'."""
    grew = {**GROWTH, "survey_lines": [{"practice": "Cyber", "line": "cyber", "score": 6.25,
                                        "delta": -0.39, "prior_year": 2024}]}
    line = D.growth_line(grew)
    assert "The carrier survey reads differently: Cyber scored 6.25, down 0.39 on 2024." in line


def test_the_fallback_growth_line_names_what_carried_it():
    assert D.growth_line(GROWTH).startswith("Cyber carried most of the growth")
    assert D.decline_line(GROWTH) == ""


def test_the_driver_sentence_comes_straight_after_the_headline():
    from studio.template_fill import feedback

    said = feedback.points("challenges", {**DECLINE, "marsh": {}, "rank": {}, "sow": {},
                                          "peer": {}})
    assert len(said) >= 2 and said[1].startswith("Casualty is where")


def test_one_line_cannot_drive_its_own_total():
    single = {**DECLINE, "movers": [{"name": "Casualty", "delta": -5e6}]}
    assert D.driver(single) is None


# ── the prompt, and the cache that must notice it changed ────────────────────


def test_the_section_prompt_carries_the_playbook_and_the_cache_keys_on_it():
    from studio.template_fill import commentary_batch as B

    column = B.Column(field_id="f1", targets=(B.Target(0, "note:1:2:0"),), topic="challenges",
                      node="challenges", bullets=2, draft=("draft line",))
    down = B.Section("book0", "Zurich", "balanced", DECLINE, (column,))
    up = B.Section("book0", "Zurich", "balanced", GROWTH, (column,))
    pack_down, pack_up = E.build_pack(DECLINE), E.build_pack(GROWTH)
    payload = B.section_payload(down, pack_down, "")
    assert "PLAYBOOK" in payload and "qbr-decline-diagnosis" in payload
    assert B._playbook(down, pack_down) != B._playbook(up, pack_up)
    assert B.cache_key(down, column, pack_down) != B.cache_key(up, column, pack_down)


def test_the_voice_names_the_insurer_consulting_group():
    from studio.template_fill import commentary as C

    voice = C.deck_voice("balanced", "Zurich")
    assert "Insurer Consulting Group" in voice and "Insurer Consulting Leader" in voice
