"""How the deck's commentary READS — whole sentences in a consultant's voice.

The figures are covered elsewhere (``test_template_feedback.py`` proves every claim carries
its number). What is guarded here is the prose itself: a QBR page is read aloud to a
carrier's executive team, so a line has to be a finished sentence rather than a chart
caption, and an LLM rewrite has to be an improvement on the deterministic draft or it is
thrown away.

Pure and hermetic: synthetic fact sets, no DB, no LLM.
"""
from __future__ import annotations

import pytest

from studio.template_fill import commentary as CM
from studio.template_fill import feedback as F

# One growing book and one shrinking one — between them they reach every composer branch.
_GROWING = {
    "carrier": {"current": 48e6, "pct": 52.5, "delta": 16e6, "current_year": 2025},
    "marsh": {"current": 411e6, "pct": 9.8},
    "rank": {"current": 2, "delta": 4, "of_n": 12},
    "sow": {"current": 11.6, "delta": 3.2},
    "peer": {"current": 45e6, "pct": 7.6, "sow": 10.8, "sow_delta": -0.2},
    "movers": [{"name": "Cyber", "delta": 12e6, "pct": 40.0},
               {"name": "Marine", "delta": -1e6, "pct": -4.0}],
    "pool": [{"name": "Cyber", "delta": 20e6}, {"name": "Property", "delta": 30e6}],
}
_SHRINKING = {
    "carrier": {"current": 30e6, "pct": -12.0, "delta": -4e6, "current_year": 2025},
    "marsh": {"current": 100e6, "pct": 2.0},
    "rank": {"current": 6, "delta": -2, "of_n": 41},
    "sow": {"current": 4.0, "delta": -1.1},
    "peer": {"current": 20e6, "pct": 1.0, "sow": 5.0, "sow_delta": 0.1},
    "movers": [{"name": "Marine", "delta": -3e6, "pct": -14.0},
               {"name": "Cyber", "delta": -1e6, "pct": -5.0}],
    "pool": [{"name": "Marine", "delta": 2e6}, {"name": "Property", "delta": 5e6}],
}

_ALL_POINTS = [p
               for facts in (_GROWING, _SHRINKING)
               for kind in F._COMPOSERS
               for p in F.points(kind, facts)
               if p != "Key Highlights:"]          # the highlights table's own heading


# ── the deterministic draft is what ships, so it has to read ─────────────────


@pytest.mark.parametrize("point", _ALL_POINTS)
def test_every_composed_point_is_a_whole_sentence(point):
    assert point[0].isupper(), "a bullet opens a sentence, not a fragment"
    assert point.endswith("."), "a bullet ends a sentence, not a caption"
    assert len(point.split()) >= 6, "a one-clause label is not commentary"


@pytest.mark.parametrize("point", _ALL_POINTS)
def test_no_point_reads_as_a_spreadsheet_cell(point):
    # Direction belongs in the verb ("grew 12.0%"), not in a sign glued to the number, and
    # "Topic: value" is a label rather than a sentence.
    assert "+" not in point.replace("+/-", "")
    assert "YoY" not in point
    assert ": " not in point


@pytest.mark.parametrize("point", _ALL_POINTS)
def test_no_point_reads_as_generated(point):
    assert CM._AI_TELLS.search(point) is None


def test_a_shrinking_book_is_not_told_it_offset_gains():
    """"Offsetting the gains elsewhere" is only true of a book that made gains; on a book
    that shrank, the lines given back ARE the decline."""
    text = " ".join(F.points("challenges", _SHRINKING))
    assert "given back on Marine" in text and "offset the gains" not in text
    assert "offset the gains" in " ".join(F.points("challenges", _GROWING))


def test_an_immaterial_movement_is_not_named_as_a_finding():
    """Naming a $145K move on a $208M book is what makes commentary read as generated: it
    is noise, and a partner would not have mentioned it."""
    noise = {**_GROWING, "movers": [{"name": "Cyber", "delta": 12e6, "pct": 40.0},
                                    {"name": "Casualty", "delta": -145e3, "pct": -0.4}]}
    text = " ".join(F.points("working", noise))
    assert "Cyber" in text and "Casualty" not in text
    assert not F.points("challenges", noise), "an immaterial faller is not a challenge"


def test_named_movers_are_joined_so_the_pair_cannot_blur():
    # "Cyber, up $12M and Marine, up $2M" reads as three things; the comma before "and"
    # is what keeps it two.
    joined = F._named_moves([{"name": "Cyber", "delta": 12e6, "pct": 40.0},
                             {"name": "Property", "delta": 8e6, "pct": 12.0}], rising=True)
    assert joined == "Cyber, up $12M (40.0%), and Property, up $8M (12.0%)"


def test_the_carrier_is_named_where_the_facts_carry_its_name():
    # A partner names the account. "The account" is only the fallback for a fact set that
    # does not know the subject (the composers are called with synthetic facts in tests).
    named = " ".join(F.points("key_messages", {**_GROWING, "subject": "Zurich"}))
    assert "Zurich wrote $48M with Marsh" in named and "The account" not in named
    assert "The account wrote $48M with Marsh" in " ".join(F.points("key_messages", _GROWING))


def test_the_peer_average_benchmarks_the_share_not_the_rank():
    # A top-5 peer SHARE average says nothing about a rank, so it must never hang off one.
    line = next(p for p in F.points("key_messages", _GROWING) if "ranks " in p)
    assert "ranks #2 of 12 and holds 11.6% of the wallet" in line
    assert line.index("top-5 peer average") > line.index("of the wallet")


# ── the summary page's prose columns come from the same composers ────────────


@pytest.mark.parametrize("topic", sorted(CM._TOPIC_PANELS))
def test_each_prose_column_is_answered_by_the_panel_composers(topic):
    points = CM._topic_points(None, topic, _GROWING)
    assert points and all(p.endswith(".") for p in points)
    assert points == list(dict.fromkeys(points)), "a column must not repeat itself"


def test_a_column_falls_back_to_the_narrator_when_there_are_no_panel_facts(monkeypatch):
    """A thin book or a dataset with no peer benchmark still gets commentary — the
    rule-based narrator answers instead of the page shipping the template's ellipsis."""
    monkeypatch.setattr(CM, "_narrated_points", lambda result, topic: ["Nothing moved."])
    assert CM._topic_points(None, "reflections", {}) == ["Nothing moved."]


# ── an LLM rewrite has to earn its place ─────────────────────────────────────


def _draft(n: int) -> str:
    return "\n".join(f"The account wrote ${i}M with Marsh." for i in range(n))


def test_a_rewrite_that_keeps_the_bullets_whole_is_accepted():
    lines = ["The account grew its book 12.0%.", "Share of wallet rose 1.0pp."]
    assert CM._accept(lines, wanted=2, node="t") == "\n".join(lines)


def test_a_rewrite_that_changes_the_bullet_count_is_refused():
    assert CM._accept(["One sentence only."], wanted=2, node="t") is None


def test_a_rewrite_that_leaves_a_fragment_is_refused():
    assert CM._accept(["Momentum: Cyber", "A whole sentence."], wanted=2, node="t") is None


def test_a_rewrite_that_reads_as_generated_is_refused():
    assert CM._accept(["Growth was 12.0%, indicating a solid foothold."],
                      wanted=1, node="t") is None


def test_the_polish_verifies_each_bullet_rather_than_the_whole_blob(monkeypatch):
    """The whole-text verifier joins the sentences it keeps with spaces, which would flatten
    a four-bullet column into one line — and then fail the line count for the wrong reason,
    so no rewrite could ever land. Bullets are verified one by one."""
    from studio.ai import client

    rewrite = "\n".join(["The account wrote $0M with Marsh, and held it.",
                         "The account wrote $1M with Marsh, and held it.",
                         "The account wrote $2M with Marsh, and held it."])
    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "generate", lambda *a, **k: rewrite)
    assert CM._polish(_draft(3), node="t") == rewrite


def test_a_polished_bullet_with_an_invented_number_is_refused(monkeypatch):
    from studio.ai import client

    monkeypatch.setattr(client, "llm_available", lambda: True)
    monkeypatch.setattr(client, "generate",
                        lambda *a, **k: "The account wrote $99M with Marsh, and held it.")
    assert CM._polish(_draft(1), node="t") == _draft(1)
