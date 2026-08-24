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
    # The challenges column still says something (no cell ships blank), but what it says is
    # the position's own standing — never the $145K faller dressed up as a finding.
    assert "Casualty" not in " ".join(F.points("challenges", noise))


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
    # Selected on the WALLET clause: the stance line that now opens the column mentions the
    # rank too, and this rule is about the sentence that carries the benchmark.
    line = next(p for p in F.points("key_messages", _GROWING) if "of the wallet" in p)
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
    lines = ["The account grew its book 12.0%.",
             "One point of wallet share came back, worth 1.0pp."]
    assert CM._accept(lines, wanted=2, node="t") == "\n".join(lines)


def test_a_rewrite_that_changes_the_bullet_count_is_refused():
    assert CM._accept(["One sentence only."], wanted=2, node="t") is None


def test_a_rewrite_that_leaves_a_fragment_is_refused():
    assert CM._accept(["Momentum: Cyber", "A whole sentence."], wanted=2, node="t") is None


def test_a_rewrite_that_reads_as_generated_is_refused():
    assert CM._accept(["Growth was 12.0%, indicating a solid foothold."],
                      wanted=1, node="t") is None


# ── the model may now EDIT, not just re-word ─────────────────────────────────
#
# The old contract was "return exactly the same number of lines", which left the model
# nothing to do but swap adjectives — and threw away any rewrite that came back a line
# short because the verifier had dropped an unfaithful bullet. Folding two thin claims into
# one sentence is the single most consultant-like move available, so one merge is allowed.


def test_one_merged_bullet_is_allowed():
    lines = ["The book grew 12.0% while wallet share came back 1.0pp.",
             "Cyber carried the gain.", "Marine gave premium back."]
    assert CM._accept(lines, wanted=4, node="t") == "\n".join(lines)


def test_two_merges_are_not_an_edit_but_a_different_page():
    assert CM._accept(["The book grew 12.0%.", "Cyber carried it."],
                      wanted=4, node="t") is None


def test_a_short_column_is_never_halved():
    """One merge on a two-bullet column would leave a single line — not an edit."""
    assert CM.min_lines(4) == 3 and CM.min_lines(3) == 2
    assert CM.min_lines(2) == 2 and CM.min_lines(1) == 1


# ── the roll-call is refused ─────────────────────────────────────────────────


def test_a_rewrite_that_names_the_carrier_on_every_line_is_refused():
    """"Zurich wrote …", "Zurich ranks …" is the loudest generated-text tell there is."""
    lines = ["Zurich grew its book 12.0% on the year.",
             "Zurich ranks 2nd and holds 11.6% of the wallet."]
    assert CM._accept(lines, wanted=2, node="t", subject="Zurich") is None


def test_naming_the_carrier_once_is_how_a_column_introduces_itself():
    lines = ["Zurich grew its book 12.0% on the year.",
             "The book ranks 2nd and holds 11.6% of the wallet."]
    assert CM._accept(lines, wanted=2, node="t", subject="Zurich") == "\n".join(lines)


def test_a_rewrite_that_leaves_a_metric_read_out_is_refused():
    """A measure and a value with a full stop on the end is a table row, not a sentence."""
    assert CM._accept(["Rank within the Marsh book improved 4 places to 2nd."],
                      wanted=1, node="t") is None
    assert CM._accept(["Share of wallet rose 3.2pp to 11.6%."], wanted=1, node="t") is None


def test_a_measure_that_says_why_or_so_what_is_kept():
    """The gate targets read-outs, not measures. A gate on the OPENING alone refused good
    rewrites too — and a refused rewrite sends the page back to the very draft we are
    trying to improve on."""
    earned = ["Momentum sits with Cyber, up $22M, so the renewal book there is what to "
              "protect first."]
    assert CM._accept(earned, wanted=1, node="t") == earned[0]


def test_the_prompt_tells_the_model_the_rule_it_is_held_to():
    """A gate the prompt never mentions just costs a call and falls back to the draft."""
    system = CM._style_system("balanced", topic="challenges", wanted=4, subject="Zurich")
    assert "Zurich" in system and "the book" in system
    assert "bare measure and a value" in system
    assert "merge two bullets" in system                  # the structural permission
    assert "THIS COLUMN" in system and "MECHANISM" in system   # the column's own brief


def test_every_column_is_briefed_differently():
    """Key Messages and Challenges draw on the SAME six figures — without separate briefs
    the model has no reason to write them apart, which is why they read alike."""
    briefs = {t: CM._TOPIC_BRIEF[t] for t in ("key_messages", "challenges", "priorities",
                                              "thesis", "performance", "reflections")}
    assert len(set(briefs.values())) == len(briefs)
    for topic, brief in briefs.items():
        assert CM._style_system("balanced", topic=topic, wanted=3).count(brief) == 1


def test_commentary_does_not_run_on_the_mechanical_tier():
    """`fast` is the tier core.initialization reserves for inner-loop nodes; the commentary
    IS the deliverable."""
    assert CM._COMMENTARY_TIER == "balanced"


# ── the model now writes from EVIDENCE, and both verifiers rule on it ────────
#
# `_rewrite` no longer hands the model a sentence to re-word. It builds an evidence pack
# from the same facts the composers used, hands over the ICG definitions of the terms in
# play, and takes back cited sentences — so these stub `client.structured`, not `generate`.


def _facts(**over):
    base = {
        "subject": "Zurich",
        "carrier": {"current": 208e6, "pct": 28.6, "delta": 46e6, "current_year": 2025},
        "marsh": {"current": 2.3e9, "pct": 9.9},
        "rank": {"current": 5, "delta": 1, "of_n": 12},
        "sow": {"current": 9.1, "delta": 1.3},
        "peer": {"current": 180e6, "sow": 10.8},
        "movers": [{"name": "Cyber", "delta": 22e6, "pct": 97.3}],
        "pool": [{"name": "Casualty", "delta": 45e6}],
    }
    base.update(over)
    return base


def _column(*bullets):
    """A `CommentaryColumn` as the model would return it, citing nothing in particular."""
    from studio.ai.models import CommentaryBullet, CommentaryColumn

    return CommentaryColumn(bullets=[CommentaryBullet(text=b, fact_ids=[]) for b in bullets])


def _stub_model(monkeypatch, column, *, verdicts=None):
    """Point the writer at a canned column and the claim judge at canned verdicts."""
    from studio.ai import client
    from studio.ai.models import CommentaryColumn, CommentaryVerdicts

    monkeypatch.setattr(client, "llm_available", lambda: True)

    def structured(model, system, user, **kw):
        if model is CommentaryColumn:
            return column
        if model is CommentaryVerdicts:
            return verdicts
        return None

    monkeypatch.setattr(client, "structured", structured)


def test_the_model_writes_the_column_from_the_evidence(monkeypatch):
    written = ("The book outgrew the Marsh pool by nearly nineteen points, taking $46M more "
               "premium in a market that grew 9.9%.",
               "At 9.1% of the wallet it still sits behind a top-5 peer average of 10.8%.")
    _stub_model(monkeypatch, _column(*written))
    out = CM._rewrite(_draft(2), node="t", subject="Zurich", facts=_facts())
    assert out.splitlines() == list(written)


def test_an_invented_figure_is_dropped_before_the_judge_ever_sees_it(monkeypatch):
    """The numeric verifier runs FIRST — cheap, exact, and it removes the worst failure."""
    _stub_model(monkeypatch, _column(
        "The book grew to $208M with Marsh, taking share as it went.",
        "Share of wallet reached 44.4%, well clear of the field."))          # invented
    out = CM._rewrite(_draft(2), node="t", subject="Zurich", facts=_facts())
    assert out == _draft(2), "one line left is below the floor, so the draft stands"


def test_the_claim_judge_drops_an_unsupported_claim(monkeypatch):
    """No bad number, but 'market leader' is a definitional overstatement — exactly what
    the deterministic verifier cannot see and the model verifier exists for."""
    from studio.ai.models import CommentaryVerdict, CommentaryVerdicts

    kept = ("The book outgrew the Marsh pool and took $46M more premium than a year ago.",
            "Cyber carried $22M of that, so the renewal there is what to defend first.",
            "At 9.1% of the wallet the book still trails a top-5 peer average of 10.8%.")
    _stub_model(
        monkeypatch,
        _column(*kept, "That makes the carrier the market leader in this segment."),
        verdicts=CommentaryVerdicts(verdicts=[
            CommentaryVerdict(keep=True), CommentaryVerdict(keep=True),
            CommentaryVerdict(keep=True),
            CommentaryVerdict(keep=False, reason="rank is a Marsh-book position, not the market"),
        ]),
    )
    out = CM._rewrite(_draft(4), node="t", subject="Zurich", facts=_facts())
    assert out.splitlines() == list(kept) and "market leader" not in out


def test_a_judge_that_answers_nonsense_is_ignored_rather_than_obeyed(monkeypatch):
    """A verdict list that does not line up must not be read as 'drop everything' — that
    blanks the page, which is worse than any sentence it might have caught."""
    from studio.ai.models import CommentaryVerdict, CommentaryVerdicts

    written = ("The book took $46M more premium than a year ago, ahead of the Marsh pool.",
               "At 9.1% of the wallet it still trails a top-5 peer average of 10.8%.")
    _stub_model(monkeypatch, _column(*written),
                verdicts=CommentaryVerdicts(verdicts=[CommentaryVerdict(keep=False)]))
    assert CM._rewrite(_draft(2), node="t", subject="Zurich",
                       facts=_facts()).splitlines() == list(written)


def test_with_no_evidence_the_draft_stands(monkeypatch):
    """A thin book builds no pack, so there is nothing to write from and nothing to cite."""
    _stub_model(monkeypatch, _column("Anything at all, really, in a whole sentence."))
    assert CM._rewrite(_draft(2), node="t", subject="Zurich", facts={}) == _draft(2)


def test_ai_off_never_calls_a_model(monkeypatch):
    """`STUDIO_AI=off` is a factory decision, not a branch in the caller."""
    from studio.ai import client
    from studio.template_fill import commentary_writer as W

    monkeypatch.setattr(client, "llm_available", lambda: False)
    monkeypatch.setattr(client, "structured", lambda *a, **k: pytest.fail("model was called"))
    assert CM._rewrite(_draft(3), node="t", subject="Zurich", facts=_facts()) == _draft(3)
    assert W.make_writer() is W.compose_from_rules
