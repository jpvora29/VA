"""The editorial plan: one finding, one home, and the gate that holds a page to it.

The failure these cover is the one a reader reports as "the deck says the same thing three
times". It is not a repeated string and the existing checks are blind to it: on a real
shipped deck one slide said the book was 1.7 percentage points behind the peer average,
that the same distance was about $39M of premium, and that reaching peer parity was worth
about $39M — three sentences, three different figures between them, one finding.

So there are three things to hold:

  * a finding is identified by what it IS, not by the unit it is rendered in
    (:func:`editorial.claim_key`, :func:`editorial.topic_of`);
  * a page allocates its findings BEFORE it is written, one home each, and every column
    gets somewhere to go — the plan must not thin a page, which is the documented failure
    mode of dedupe on its own (see :mod:`studio.template_fill.ledger`);
  * the gate drops only a REPEAT, keeps the home's copy, and never empties a field.

No LLM and no database: the model is a stub answering the structured schema, so what is
under test is the plan and the gate rather than the writing.
"""
from __future__ import annotations

import pytest

from studio.ai.models import CommentaryBullet, CommentarySection, CommentarySections
from studio.template_fill import commentary_batch as B
from studio.template_fill import commentary_qa as QA
from studio.template_fill import editorial as E
from studio.template_fill.rewrites import PendingRewrite


# ── fixtures ─────────────────────────────────────────────────────────────────

#: The five columns a summary page carries — the page the repetition was found on.
_SUMMARY = ("thesis", "key_messages", "performance", "priorities", "reflections")


def _columns(topics=_SUMMARY, page: int = 1):
    return tuple(B.Column(field_id=f"{page}.{topic}",
                          targets=(B.Target(0, f"note:{page}:{i}:0"),),
                          topic=topic, node=f"p{page}-{topic}", bullets=2)
                 for i, topic in enumerate(topics))


def _facts() -> dict:
    """A fact dict of the shape ``feedback.facts_for`` returns, big enough to cite."""
    return {
        "subject": "Zurich",
        "carrier": {"current": 44_000_000.0, "pct": 12.8, "delta": 5_000_000.0,
                    "current_year": 2025},
        "marsh": {"current": 900_000_000.0, "pct": 6.2},
        "sow": {"current": 4.9, "delta": 0.5},
        "rank": {"current": 4, "of_n": 31, "delta": 1},
        "peer": {"sow": 6.1, "current": 55_000_000.0},
    }


def _value_set(facts: dict, topics=("thesis", "key_messages", "priorities")) -> dict:
    return {f"note:1:{i}:0": PendingRewrite(
        draft=f"{topic} line one.\n{topic} line two.", node=f"commentary-{topic}",
        topic=topic, subject="Zurich", style="balanced", facts=facts)
        for i, topic in enumerate(topics)}


@pytest.fixture(autouse=True)
def _no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_COMMENTARY_CACHE", str(tmp_path / "commentary"))
    monkeypatch.setenv("COMMENTARY_MODE", "auto")
    monkeypatch.delenv("STUDIO_AI", raising=False)


# ── what makes two sentences one finding ─────────────────────────────────────


def test_a_gap_in_points_and_the_same_gap_in_premium_are_one_topic():
    """``peer.gap`` and ``peer.gap_value`` are one distance rendered twice."""
    assert E.topic_of_fact("peer.gap") == "peer_gap"
    assert E.topic_of_fact("peer.gap_value") == "peer_gap"
    assert E.topic_of_fact("share.point_value") == "peer_gap"
    assert E.topic_of_fact("mover.cyber") == E.topic_of_fact("pool.cyber") == "movement"


def test_the_claim_key_is_blind_to_the_unit_the_finding_is_rendered_in():
    """The three sentences off the shipped slide collapse to one key."""
    points = "Share of wallet rose 1.3pp to 9.1%, which leaves the book 1.7pp below the " \
             "top-5 peer average of 10.8%."
    premium = "At 9.1% share of wallet the book sits 1.7pp below the top-5 peer average " \
              "of 10.8%, which is about $39M of premium in scope."
    parity = "Reaching peer parity means winning 1.7pp of share, worth about $39M of GWP."
    assert E.claim_key(points) == E.claim_key(premium) == E.claim_key(parity)


def test_the_same_finding_about_two_products_stays_two_findings():
    """The driver is part of the key, so a per-product page is not deduped into silence."""
    cyber = "Cyber sits 2.0pp below the top-5 peer average, worth about $8M of premium."
    property_ = "Property sits 3.1pp below the top-5 peer average, worth about $12M."
    whole = "The book sits 1.7pp below the top-5 peer average, worth about $39M."
    assert E.claim_key(cyber) != E.claim_key(property_) != E.claim_key(whole)


def test_a_finding_and_its_reverse_are_not_the_same_claim():
    below = "The book sits 1.7pp below the top-5 peer average."
    above = "The book sits 1.7pp above the top-5 peer average."
    assert E.claim_key(below) != E.claim_key(above)


def test_citations_beat_wording_when_a_bullet_carries_both():
    """A sentence that cites its facts is placed by them, not by the words it used."""
    assert E.topic_of(("headroom.cyber",), "the book ranks fourth") == "headroom"


def test_a_cited_claim_is_identified_without_needing_a_direction_word():
    """The words fail where the ids do not: only one of these says which way it points."""
    behind = "The book sits 1.7pp below the top-5 peer average."
    closing = "Closing that gap would add roughly $39M of GWP."
    assert E.claim_key(behind) != E.claim_key(closing), "the words alone cannot connect them"
    assert E.claim_of(("peer.gap",), behind) == E.claim_of(("peer.gap_value",), closing)


def test_two_industries_in_one_fact_family_are_two_findings():
    """The gate keys on the CLAIM, not the family — or a whitespace column loses its list."""
    cyber = E.claim_of(("segment.industry.absent.cyber",), "Marsh places $40M in Cyber.")
    marine = E.claim_of(("segment.industry.absent.marine",), "Marsh places $18M in Marine.")
    assert cyber != marine
    assert E.entity_of_fact("mover.cyber") == "cyber"
    assert E.entity_of_fact("segment.industry.absent.renewable_energy") == "renewable_energy"
    assert E.entity_of_fact("peer.gap") == ""


def test_a_column_listing_three_whitespace_industries_keeps_all_three():
    plan = E.plan_deck([_columns()])
    owner = next(c.field_id for c in _columns()
                 if "headroom" in plan.fields[c.field_id].owns)
    kept, dropped = E.dedupe(_bullets(
        (owner, "Marsh places $40M of Cyber this book writes none of.",
         ("segment.industry.absent.cyber",)),
        (owner, "Marine is the same story at $18M.", ("segment.industry.absent.marine",)),
        (owner, "Energy adds a further $11M of the same.",
         ("segment.industry.absent.energy",)),
    ), plan=plan)
    assert not dropped
    assert len(kept[owner]) == 3


# ── the allocation ───────────────────────────────────────────────────────────


def test_every_column_on_a_page_gets_a_finding_of_its_own():
    """Five columns, five distinct homes — the point of the round-robin draft."""
    plan = E.plan_deck([_columns()])
    owned = {c.field_id: plan.fields[c.field_id].owns for c in _columns()}
    assert all(topics for topics in owned.values()), owned
    homes = [t for topics in owned.values() for t in topics]
    assert len(homes) == len(set(homes)), "a finding was given two homes"


def test_the_peer_gap_has_exactly_one_home_on_the_page():
    """Four of the five columns lead from ``peer.`` — only one may own it."""
    plan = E.plan_deck([_columns()])
    owners = [c.field_id for c in _columns()
              if "peer_gap" in plan.fields[c.field_id].owns]
    assert len(owners) == 1


def test_a_field_is_told_what_the_other_fields_own_and_that_units_do_not_help():
    plan = E.plan_deck([_columns()])
    owner = next(c.field_id for c in _columns()
                 if "peer_gap" in plan.fields[c.field_id].owns)
    others = [c.field_id for c in _columns() if c.field_id != owner]
    for field_id in others:
        brief = plan.brief(field_id)
        assert "in points OR in premium" in brief
        assert "not in another unit" in brief, "the units clause is the point of the ban"
        # The ban is on making it YOUR POINT, not on mentioning it: a movement needs the
        # book it moved against, and forbidding the comparison outright is what left the
        # overall page unable to mention premium at all.
        assert "YOUR POINT" in brief
        assert "MAY cite one in passing" in brief


def test_the_allocation_is_deterministic():
    first = E.plan_deck([_columns()])
    second = E.plan_deck([_columns()])
    assert {k: v.owns for k, v in first.fields.items()} == \
           {k: v.owns for k, v in second.fields.items()}


def test_a_page_with_one_field_gets_no_plan_because_it_cannot_repeat_itself():
    plan = E.plan_deck([_columns(("thesis",))])
    assert plan.is_empty()


def test_a_field_left_without_a_home_is_given_the_synthesis_job():
    """More fields than findings: the surplus synthesises rather than writing unplanned.

    It used to get no plan at all — no job and no ban list — because handing it only the
    ban list forbids every finding on the page and offers nothing in exchange. The
    consequence was worse than the problem: the fields the allocation leaves over are the
    summary ones (Key Messages, Carrier Priorities), and unplanned they simply restated
    the page. That was the reported repetition. They now get the one job no owning field
    is free to do — the forward view.
    """
    crowded = _columns(("thesis", "key_messages", "performance", "priorities",
                        "reflections", "working", "challenges", "growth"))
    plan = E.plan_deck([crowded])
    homed = surplus = 0
    for column in crowded:
        brief = plan.brief(column.field_id)
        assert brief, "every field on a crowded page now gets a job"
        if "THIS FIELD IS THE HOME FOR" in brief:
            homed += 1
        else:
            surplus += 1
            assert "SYNTHESIS" in brief
            assert "PROTECT" in brief, "the forward view is what it is for"
            assert "only repeats a finding is a wasted line" in brief
    assert homed and surplus, "this page must exercise both branches"


def test_the_second_page_to_reach_for_a_finding_is_told_to_add_something():
    plan = E.plan_deck([_columns(_SUMMARY, page=1), _columns(("working", "growth"), page=2)])
    recapped = [plan.brief(c.field_id) for c in _columns(("working", "growth"), page=2)]
    assert any("ALREADY MADE EARLIER IN THIS DECK" in brief for brief in recapped)
    assert all("ALREADY MADE EARLIER" not in plan.brief(c.field_id)
               for c in _columns(_SUMMARY, page=1))


# ── the gate ─────────────────────────────────────────────────────────────────


def _bullets(*items):
    """``(field_id, text, fact_ids)`` or ``(field_id, text, fact_ids, kind)``."""
    return [tuple(item) for item in items]


# ── ownership is per SLIDE, not per book ────────────────────────────────────


def _overall_book():
    """The real overall template's shape: the headline page, then the summary page.

    Slide 2 is "Positive Growth and Market Leadership Highlights" and carries ONE prose
    box (``thesis``) beside its own KPI tiles — premium, premium YoY, country YoY, share
    of Marsh premium, rank. Slide 3 is "Carrier Trading Summary with Marsh" and carries
    four (YTD Performance, 2025 Reflections, Carrier Priorities, Key Messages).
    """
    def column(slide, i, topic):
        return B.Column(field_id=f"{slide}.{topic}",
                        targets=(B.Target(0, f"note:{slide}:{i}:0"),),
                        topic=topic, node=f"s{slide}-{topic}", bullets=2)

    return (column(2, 34, "thesis"),
            column(3, 10, "performance"), column(3, 16, "reflections"),
            column(3, 20, "priorities"), column(3, 22, "key_messages"))


def test_the_headline_page_is_not_stripped_of_premium_by_the_next_slide():
    """The reported bug: the overall page could not mention the KPIs printed on it.

    Allocation ran over a whole BOOK, which spans slides, so ``scale`` — premium and the
    Marsh pool around it — went to Key Messages on slide 3 and the headline box on slide 2
    was then forbidden to make that point "in any form". The page's biggest tile is
    "$xxx.xm Premium written with Marsh" and its only prose box could not discuss it.
    """
    columns = _overall_book()
    plan = E.plan_deck([columns])
    headline = plan.fields.get("2.thesis")
    brief = plan.brief("2.thesis")
    # Slide 2 has one prose box, so there is nobody to divide findings with and nothing to
    # ban. What matters is that it is not handed another slide's ban list.
    assert "the size of the book" not in brief, "premium must not be banned on this page"
    assert headline is None or "scale" not in dict(headline.elsewhere or ())


def test_the_summary_slide_still_divides_its_own_findings():
    """Per-slide allocation must not become no allocation: slide 3's four boxes share out."""
    plan = E.plan_deck([_overall_book()])
    owners = {fid: plan.fields[fid].owns for fid in
              ("3.performance", "3.reflections", "3.priorities", "3.key_messages")
              if fid in plan.fields}
    assert owners, "the four-box slide must still be planned"
    claimed = [t for owns in owners.values() for t in owns]
    assert len(claimed) == len(set(claimed)), "one finding cannot have two homes on a slide"


def test_a_later_slide_reaching_for_the_headline_finding_is_told_to_add_something():
    """Cross-page repetition is the recap rule's job, and it still runs deck-wide."""
    plan = E.plan_deck([_overall_book()])
    briefs = [plan.brief(f"3.{t}") for t in
              ("performance", "reflections", "priorities", "key_messages")]
    assert any("ALREADY MADE EARLIER IN THIS DECK" in b for b in briefs), \
        "slide 3 must know what slide 2 already said"


# ── the synthesis field: it may BUILD on an owned finding, not restate it ────
#
# The fields the allocation leaves without a topic are the summary ones, and their job is
# to take the page's findings forward. `claim_of` reads a bullet's identity off its FIRST
# citation, so the supporting fact a synthesis bullet names matches the owning field's
# copy — the gate would drop the one field whose purpose is to reference. The bullet's
# declared KIND is what separates building on a finding from repeating it.


def _synthesis_page():
    """A page crowded enough that the allocation leaves at least one field homeless."""
    crowded = _columns(("thesis", "key_messages", "performance", "priorities",
                        "reflections", "working", "challenges", "growth"))
    plan = E.plan_deck([crowded])
    owner = next(c.field_id for c in crowded if "peer_gap" in plan.fields[c.field_id].owns)
    synth = next(c.field_id for c in crowded if plan.fields[c.field_id].synthesis)
    return plan, owner, synth


def test_a_synthesis_field_may_build_on_a_finding_another_field_owns():
    plan, owner, synth = _synthesis_page()
    kept, dropped = E.dedupe(_bullets(
        (owner, "The book sits 1.7pp below the peer average.", ("peer.gap",), "observation"),
        (synth, "Closing that gap is where the year's plan has to start, and it means "
                "defending Cyber first.", ("peer.gap",), "recommendation"),
    ), plan=plan)
    assert not dropped, "the summary field's job is to build on what the page established"
    assert len(kept[synth]) == 1


def test_a_synthesis_field_restating_a_finding_still_loses_it():
    """The exemption is for ADDING something, and 'observation' says it added nothing.

    Without this the one-finding-one-page guarantee stops holding the moment a page
    carries a summary field, which is every page.
    """
    plan, owner, synth = _synthesis_page()
    kept, dropped = E.dedupe(_bullets(
        (owner, "The book sits 1.7pp below the peer average.", ("peer.gap",), "observation"),
        (synth, "The book is 1.7pp behind the peer benchmark.", ("peer.gap",), "observation"),
    ), plan=plan)
    assert [d.field_id for d in dropped] == [synth]
    assert kept[synth] == []


def test_an_owning_field_gets_no_exemption_however_it_tags_its_bullet():
    """Only the homeless field synthesises; a field with a topic argues its own finding."""
    plan = E.plan_deck([_columns()])
    owner = next(c.field_id for c in _columns()
                 if "peer_gap" in plan.fields[c.field_id].owns)
    other = next(c.field_id for c in _columns()
                 if c.field_id != owner and not plan.fields[c.field_id].synthesis)
    kept, dropped = E.dedupe(_bullets(
        (owner, "The book sits 1.7pp below the peer average.", ("peer.gap",), "observation"),
        (other, "That distance is the year's priority.", ("peer.gap",), "recommendation"),
    ), plan=plan)
    assert [d.field_id for d in dropped] == [other]


def test_the_home_keeps_the_finding_and_the_other_fields_lose_their_copy():
    plan = E.plan_deck([_columns()])
    owner = next(c.field_id for c in _columns()
                 if "peer_gap" in plan.fields[c.field_id].owns)
    other = next(c.field_id for c in _columns() if c.field_id != owner)
    kept, dropped = E.dedupe(_bullets(
        (other, "The book sits 1.7pp below the peer average.", ("peer.gap",)),
        (other, "Growth came from Cyber, which added $22M against a flat pool.",
         ("mover.cyber",)),
        (owner, "Closing the peer gap is worth about $39M.", ("peer.gap_value",)),
    ), plan=plan)
    assert kept[owner] == ["Closing the peer gap is worth about $39M."]
    assert [d.field_id for d in dropped] == [other]
    assert len(kept[other]) == 1


def test_a_finding_only_one_field_claimed_is_never_dropped():
    """The gate is a repetition rule, not an ownership rule — it may not thin a page."""
    plan = E.plan_deck([_columns()])
    not_the_owner = next(c.field_id for c in _columns()
                         if "peer_gap" not in plan.fields[c.field_id].owns)
    kept, dropped = E.dedupe(_bullets(
        (not_the_owner, "The book sits 1.7pp below the peer average.", ("peer.gap",)),
    ), plan=plan)
    assert not dropped
    assert kept[not_the_owner] == ["The book sits 1.7pp below the peer average."]


def test_a_field_that_wrote_only_repeats_is_emptied_and_told_why():
    """No "keep the last line" exception — that is what put the repeat back on the page.

    A field left with nothing becomes a failure carrying the reason, which is what sends
    it to the repair round; :func:`test_a_deck_whose_writer_repeats_one_finding_ships_it_once`
    covers where it lands when repair cannot help either.
    """
    plan = E.plan_deck([_columns()])
    owner = next(c.field_id for c in _columns()
                 if "peer_gap" in plan.fields[c.field_id].owns)
    other = next(c.field_id for c in _columns() if c.field_id != owner)
    kept, dropped = E.dedupe(_bullets(
        (owner, "Closing the peer gap is worth about $39M.", ("peer.gap_value",)),
        (other, "The book sits 1.7pp below the peer average.", ("peer.gap",)),
        (other, "Reaching parity means winning 1.7pp of share.", ("peer.gap",)),
    ), plan=plan)
    assert kept[other] == []
    assert len(dropped) == 2
    assert all("already makes on this page" in d.reason for d in dropped)


def test_without_a_plan_the_first_copy_in_page_order_wins():
    kept, dropped = E.dedupe(_bullets(
        ("a", "The book sits 1.7pp below the peer average.", ("peer.gap",)),
        ("a", "Cyber added $22M against a flat pool.", ("mover.cyber",)),
        ("b", "Closing that gap is worth about $39M.", ("peer.gap_value",)),
    ))
    assert kept["b"] == []
    assert [d.field_id for d in dropped] == ["b"]


def test_a_bullet_that_cited_nothing_is_still_compared_with_one_that_did():
    """The seam: the two identities must be the same shape or a repeat slips between them."""
    kept, dropped = E.dedupe(_bullets(
        ("a", "The book sits 1.7pp below the top-5 peer average.", ("peer.gap",)),
        ("b", "The book sits 1.7pp below the top-5 peer average of 10.8%.", ()),
    ))
    assert [d.field_id for d in dropped] == ["b"]
    assert kept["a"] and not kept["b"]


def test_a_bullet_in_no_fact_family_is_left_alone():
    kept, dropped = E.dedupe(_bullets(
        ("a", "The task here is holding what the year won.", ()),
        ("b", "The task here is holding what the year won, twice.", ()),
    ))
    assert not dropped and kept["a"] and kept["b"]


# ── the finished deck ────────────────────────────────────────────────────────


def test_qa_reports_one_finding_said_three_ways_across_a_page():
    """The exact-string rule sees none of these; the equivalence rule sees all three."""
    cells = {
        "note:16:1:0": "Share of wallet rose 1.3pp to 9.1%, which leaves the book 1.7pp "
                       "below the top-5 peer average of 10.8%.",
        "note:16:2:0": "At 9.1% share of wallet the book sits 1.7pp below the top-5 peer "
                       "average of 10.8%, which is about $39M of premium in scope.",
        "note:16:3:0": "Reaching peer parity means winning 1.7pp of share, worth about "
                       "$39M of GWP.",
    }
    codes = {issue.code for issue in QA.check(cells)}
    assert "equivalent_claim" in codes
    assert "repeated_claim" not in codes, "no string repeats here — that is the point"
    issue = next(i for i in QA.check(cells) if i.code == "equivalent_claim")
    assert len(issue.where) == 3


def test_qa_does_not_report_two_products_making_the_same_shape_of_point():
    cells = {
        "note:9:1:0": "Cyber sits 2.0pp below the top-5 peer average, worth about $8M.",
        "note:9:2:0": "Property sits 3.1pp below the top-5 peer average, worth about $12M.",
    }
    assert not [i for i in QA.check(cells) if i.code == "equivalent_claim"]


# ── end to end, through the section writer ───────────────────────────────────


@pytest.fixture
def repeating_model(monkeypatch):
    """A model that answers every field with the SAME finding in a different unit.

    Which is what the real one did on the deck this work came from. Returns the call log
    so a test can read the prompt each field was actually given.
    """
    import studio.ai.client as client

    calls = []

    def structured(model, system, user, *, tier="balanced", node="ai", phase="other",
                   fields=(), **kw):
        calls.append({"node": node, "phase": phase, "fields": tuple(fields), "user": user})
        if model is not CommentarySections:
            import re
            from studio.ai.models import CommentaryVerdict, CommentaryVerdicts
            count = len(re.findall(r"^\d+\. ", user, re.M))
            return CommentaryVerdicts(verdicts=[CommentaryVerdict(keep=True) for _ in range(count)])
        asked = [line.split()[2] for line in user.splitlines()
                 if line.startswith("--- FIELD ")]
        renderings = [
            "The carrier sits below the peer average, and closing that is the year's "
            "work.",
            "Reaching peer parity is what the plan has to be built around this year.",
            "The distance to the peer benchmark is the single thing holding the carrier back.",
        ]
        return CommentarySections(sections=[
            CommentarySection(field_id=field_id, bullets=[
                CommentaryBullet(text=text, fact_ids=["peer.gap"]) for text in renderings
            ]) for field_id in asked])

    monkeypatch.setattr(client, "structured", structured)
    monkeypatch.setattr(client, "llm_available", lambda: True)
    return calls


def test_every_field_is_told_its_editorial_job_in_the_prompt(repeating_model):
    B.write_deck([_value_set(_facts())])
    author = next(c for c in repeating_model if c["phase"] == "author")
    assert "MATERIAL AVAILABLE TO THIS SECTION" in author["user"]
    assert "section relevance takes priority over variety" in author["user"]


def test_a_deck_whose_writer_repeats_one_finding_ships_it_once(repeating_model):
    """The end-to-end guarantee: three fields, one finding, one page that says it once.

    The stub is deliberately incorrigible — it answers the repair round with the same
    three renderings it was rejected for — so this also pins where the page lands when the
    model will not cooperate: the two fields that lost their copy fall back to their
    deterministic drafts, which the claim ledger has already made distinct.
    """
    written = B.write_deck([_value_set(_facts())])[0]
    lines = [line for text in written.values() for line in text.split("\n") if line.strip()]
    peer_gap = [E.claim_key(line) for line in lines
                if E.claim_key(line).startswith("peer_gap")]
    assert len(peer_gap) == len(set(peer_gap)), f"one finding shipped twice: {lines}"


def test_the_page_is_not_emptied_by_the_gate(repeating_model):
    """Every field still ships prose — a deduped deck must not be a blank one."""
    written = B.write_deck([_value_set(_facts())])[0]
    assert len(written) == 3
    assert all(text.strip() for text in written.values())


def test_one_finding_does_not_reach_two_pages_of_the_same_book(repeating_model):
    """The slide 6 / slide 16 case, end to end.

    Two sub-decks over one book — the shape of a single-country run, where the overall
    block's ranking page and the country block's SWOT page report the same figures. The
    writer answers every field with the peer gap. Across BOTH sub-decks it may appear once.
    """
    written = B.write_deck([_value_set(_facts()), _value_set(_facts())])
    lines = [line for page in written for text in page.values()
             for line in text.split("\n") if line.strip()]
    peer_gap = [E.claim_key(line) for line in lines
                if E.claim_key(line).startswith("peer_gap")]
    assert len(peer_gap) == len(set(peer_gap)), f"one finding on two pages: {lines}"


def test_two_pages_of_the_same_book_are_planned_against_each_other(repeating_model):
    """Both sub-decks' fields are in ONE author call, so the plan can allocate between them."""
    B.write_deck([_value_set(_facts()), _value_set(_facts())])
    authors = [c for c in repeating_model if c["phase"] == "author"]
    first = authors[0]["user"]
    assert len(first.splitlines()) > 0
    assert first.count("--- FIELD ") == 6, "both sub-decks' six fields, asked together"


def test_two_different_books_are_still_written_separately(repeating_model):
    """A product or country whose figures differ keeps its own call and its own findings."""
    other = _facts()
    other["carrier"]["current"] = 51_000_000.0
    B.write_deck([_value_set(_facts()), _value_set(other)])
    authors = [c for c in repeating_model if c["phase"] == "author"]
    assert sum(call["user"].count("--- FIELD ") == 3 for call in authors) == 2
    assert all(call["user"].count("--- FIELD ") <= 3 for call in authors)


def test_repetition_across_two_pages_of_one_book_is_reported(caplog):
    """The safety net behind the gate, at the scope the per-sub-deck check cannot reach."""
    import logging

    from studio.template_fill import commentary_qa

    issues = commentary_qa.check_book({
        "ranking-highlights": "At 9.1% share of wallet the book sits 1.7pp below the "
                              "top-5 peer average of 10.8%.",
        "country-challenges": "Reaching peer parity means winning 1.7pp of share, worth "
                              "about $39M of GWP.",
    })
    assert [i.code for i in issues] == ["equivalent_claim"]
    assert issues[0].where == ("country-challenges", "ranking-highlights")
    with caplog.at_level(logging.INFO, logger="studio.template_fill.commentary_qa"):
        commentary_qa.log_issues(issues, label="book book0")
    assert "equivalent_claim" in caplog.text


def test_the_cache_key_changes_when_a_field_is_given_a_different_job():
    """Yesterday's answer must not put yesterday's repetition back on the page."""
    from studio.template_fill import commentary_evidence as EV

    columns = _columns()
    section = B.Section("set0.0", "Zurich", "balanced", _facts(), columns)
    pack = EV.build_pack(_facts())
    plan = E.plan_deck([columns])
    assert B.cache_key(section, columns[0], pack) != \
        B.cache_key(section, columns[0], pack, plan)
