"""The evidence pack, and the two verifiers that rule on what is written from it.

The pack is what turned commentary from "reword this sentence" into "write this column".
It has to carry every fact the composers had, render each one the way the deck says it, and
attach the ICG term behind it — a fact with no term reaches the model undefended.

The verifiers catch different failures on purpose: the deterministic one cannot see meaning,
the model one cannot be trusted to see digits reliably. Both are guarded here, including
the failure paths, because a verifier that breaks open is worse than one that is absent.

Pure and hermetic: synthetic facts, stubbed model.
"""
from __future__ import annotations

import pytest

from studio.template_fill import commentary_evidence as E
from studio.template_fill import commentary_verify as V

_FACTS = {
    "subject": "Zurich",
    "carrier": {"current": 208e6, "pct": 28.6, "delta": 46e6, "current_year": 2025},
    "marsh": {"current": 2.3e9, "pct": 9.9},
    "rank": {"current": 5, "delta": 1, "of_n": 12},
    "sow": {"current": 9.1, "delta": 1.3},
    "peer": {"current": 180e6, "sow": 10.8},
    "movers": [{"name": "Cyber", "delta": 22e6, "pct": 97.3},
               {"name": "Property", "delta": -1.1e6, "pct": -6.0}],
    "pool": [{"name": "Casualty", "delta": 45e6}],
}


@pytest.fixture
def pack():
    return E.build_pack(_FACTS)


# ── what the pack carries ────────────────────────────────────────────────────


def test_every_fact_family_reaches_the_pack(pack):
    ids = {e.fact_id for e in pack.items}
    for expected in ("carrier.premium", "carrier.yoy", "marsh.premium", "marsh.yoy",
                     "rank.current", "sow.current", "sow.delta", "peer.sow",
                     "headroom", "peer.gap", "share.point_value", "mover.Cyber"):
        assert expected in ids, f"{expected} missing from the pack"


def test_a_fact_is_rendered_the_way_the_deck_says_it(pack):
    assert pack.get("carrier.premium").rendered == "$208M"
    assert pack.get("rank.current").rendered == "#5 of 12"
    assert pack.get("sow.current").rendered == "9.1%"


def test_share_movement_is_rendered_in_spelled_out_points(pack):
    """The pack is what the model reads, so 'pp' must not survive into it either."""
    assert pack.get("sow.delta").rendered == "1.3 percentage points"


def test_headroom_is_derived_rather_than_asserted(pack):
    """$2.3B Marsh book minus $208M written = what is placed with other carriers."""
    assert pack.get("headroom").rendered == "$2.1B"
    assert "other carriers" in pack.get("headroom").label.lower()


def test_the_peer_gap_and_what_closing_it_is_worth_are_both_facts(pack):
    """A model with the gap but not its value can only say 'the book trails its peers'."""
    assert pack.get("peer.gap").rendered == "1.7 percentage points"
    assert pack.get("peer.gap_value") is not None


def test_every_fact_carries_the_term_behind_it(pack):
    assert all(e.term for e in pack.items), "a fact with no ICG term reaches the model bare"


def test_the_terms_in_play_are_the_ones_the_writer_asks_to_have_defined(pack):
    from core.definitions import get_glossary

    glossary = get_glossary()
    assert all(glossary.get(term) is not None for term in pack.terms())
    assert "share_of_wallet" in pack.terms() and "headroom" in pack.terms()


def test_named_movers_are_facts_so_a_column_can_say_why(pack):
    cyber = pack.get("mover.Cyber")
    assert cyber.rendered == "$22M (97.3%)" and "added" in cyber.label


def test_a_thin_book_builds_an_empty_pack_rather_than_a_wrong_one():
    assert E.build_pack({}).items == ()
    assert E.build_pack({"subject": "Zurich"}).items == ()


def test_a_flat_share_movement_is_not_offered_as_a_finding():
    """0.02 percentage points is noise; a fact for it invites a sentence about it."""
    facts = {**_FACTS, "sow": {"current": 9.1, "delta": 0.02}}
    assert E.build_pack(facts).get("sow.delta") is None


def test_the_brief_cites_ids_the_model_can_quote_back(pack):
    brief = pack.as_brief()
    assert "[carrier.premium]" in brief and "$208M" in brief


# ── the deterministic verifier ───────────────────────────────────────────────


def _judged(text, *fact_ids):
    return [V.Judged(text=text, fact_ids=tuple(fact_ids))]


def test_a_figure_from_the_cited_fact_is_kept(pack):
    verdict = V.check_numbers(_judged("The book wrote $208M with Marsh.", "carrier.premium"),
                              pack)
    assert verdict.kept == ("The book wrote $208M with Marsh.",)


def test_an_invented_figure_is_dropped(pack):
    verdict = V.check_numbers(_judged("The book wrote $999M with Marsh.", "carrier.premium"),
                              pack)
    assert verdict.kept == () and "unsupported figure" in verdict.dropped[0].reason


def test_a_figure_from_a_fact_the_sentence_did_not_cite_is_dropped(pack):
    """Citing is a claim about which facts are in use. Quoting the peer average while
    citing only your own premium is how two figures get silently swapped."""
    verdict = V.check_numbers(
        _judged("The book holds 9.1% against a peer average of 10.8%.", "sow.current"), pack)
    assert verdict.kept == ()


def test_a_sentence_citing_nothing_is_checked_against_the_whole_pack(pack):
    """A qualitative line cites nothing by nature and must still be allowed."""
    assert V.check_numbers(_judged("The task here is defending a lead."), pack).kept


# ── the model verifier ───────────────────────────────────────────────────────


def _stub_judge(monkeypatch, verdicts):
    from studio.ai import client

    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "structured", lambda *a, **k: verdicts)


def test_the_judge_drops_a_claim_the_numbers_cannot_catch(monkeypatch, pack):
    """'Market leader' carries no bad digit — this is the whole reason it exists."""
    from studio.ai.models import CommentaryVerdict, CommentaryVerdicts

    _stub_judge(monkeypatch, CommentaryVerdicts(verdicts=[
        CommentaryVerdict(keep=False, reason="rank is a Marsh-book position")]))
    verdict = V.check_claims(_judged("The carrier is the market leader here."), pack)
    assert verdict.kept == () and "unsupported claim" in verdict.dropped[0].reason


def test_an_unavailable_judge_keeps_everything(monkeypatch, pack):
    from studio.ai import client

    monkeypatch.setattr(client, "structured", lambda *a, **k: None)
    assert V.check_claims(_judged("Anything at all."), pack).kept == ("Anything at all.",)


def test_a_misaligned_verdict_list_keeps_everything(monkeypatch, pack):
    """A judge answering with the wrong number of verdicts must not blank the page."""
    from studio.ai.models import CommentaryVerdict, CommentaryVerdicts

    _stub_judge(monkeypatch, CommentaryVerdicts(verdicts=[CommentaryVerdict(keep=False)] * 3))
    assert V.check_claims(_judged("One sentence."), pack).kept == ("One sentence.",)


# ── the two together ─────────────────────────────────────────────────────────


def test_the_numbers_run_first_so_the_judge_never_sees_a_bad_figure(monkeypatch, pack):
    seen = {}

    def structured(model, system, user, **kw):
        seen["payload"] = user
        return None

    from studio.ai import client
    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "structured", structured)

    V.verify([V.Judged("The book wrote $208M with Marsh.", ("carrier.premium",)),
              V.Judged("The book wrote $999M with Marsh.", ("carrier.premium",))], pack)
    assert "$999M" not in seen["payload"] and "$208M" in seen["payload"]


def test_the_judge_is_skipped_when_the_numbers_took_everything(monkeypatch, pack):
    from studio.ai import client

    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "structured",
                        lambda *a, **k: pytest.fail("judge ran on an empty column"))
    assert V.verify(_judged("The book wrote $999M.", "carrier.premium"), pack).kept == ()


def test_the_agent_can_be_turned_off_and_the_numbers_still_run(pack):
    verdict = V.verify(_judged("The book wrote $999M.", "carrier.premium"), pack,
                       use_agent=False)
    assert verdict.kept == ()
