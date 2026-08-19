"""The commentary rubric — and the measured proof that the roll-call fix moved it.

"The commentary is better now" is unfalsifiable, and this codebase has already lost two
commentary changes to that (the reverted per-slide cache and the spare-candidate
experiment). :mod:`studio.template_fill.commentary_metrics` turns the judgement into
proportions over the deck's own bullets so a change is argued from a number.

The last test is the one that matters: it composes a real column from real facts, scores it
with the opening fix off and on, and asserts the direction of the move.

Pure and hermetic: synthetic fact sets, no DB, no LLM.
"""
from __future__ import annotations

from studio.template_fill import commentary_metrics as M
from studio.template_fill import feedback as F
from studio.template_fill.openings import vary_openings

_FACTS = {
    "subject": "Zurich",
    "carrier": {"current": 48e6, "pct": 12.4, "delta": 5.3e6, "current_year": 2025},
    "marsh": {"current": 411e6, "pct": 7.1},
    "rank": {"current": 4, "delta": 1, "of_n": 12},
    "sow": {"current": 8.9, "delta": 0.6},
    "peer": {"current": 45e6, "pct": 7.6, "sow": 11.3, "sow_delta": -0.2},
    "movers": [{"name": "Cyber", "delta": 4e6, "pct": 40.0},
               {"name": "Property", "delta": -1.1e6, "pct": -6.0}],
    "pool": [{"name": "Cyber", "delta": 9e6}, {"name": "Property", "delta": 12e6}],
}


def _payload(*bullets: str) -> dict:
    return {"note:1:2:0": "\n".join(bullets)}


# ── what the harness reads ───────────────────────────────────────────────────


def test_it_only_scores_the_prose_roles():
    values = {"note:1:2:0": "The book grew twelve per cent on the year overall.",
              "kpi:total": "$48.2m", "drop_shapes": ["x"], "fbnote:2:3:r0c0:cell":
              "Cyber carried the whole of the gain this year."}
    assert len(M.commentary_bullets(values)) == 2


def test_a_heading_is_neither_good_nor_bad_prose():
    """"Key Highlights:" is a label the template asked for, not a claim to judge."""
    assert M.score(_payload("Key Highlights:", "Cyber carried the whole gain this year.")
                   ).bullets == 1


def test_an_empty_deck_scores_zero_rather_than_dividing_by_it():
    assert M.score({}).bullets == 0 and M.score({}).causal_rate == 0.0


# ── the five rates ───────────────────────────────────────────────────────────


def test_the_roll_call_scores_as_a_roll_call():
    rolled = M.score(_payload(
        "Zurich wrote $48.2m with Marsh in 2025, up 12.4% on the year.",
        "Zurich ranks 4th and holds 8.9% of the wallet, up 0.6pp.",
    ), subject="Zurich")
    assert rolled.subject_opening_rate == 1.0


def test_naming_the_carrier_once_halves_the_rate():
    scored = M.score(_payload(
        "Zurich wrote $48.2m with Marsh in 2025, up 12.4% on the year.",
        "The book ranks 4th and holds 8.9% of the wallet, up 0.6pp.",
    ), subject="Zurich")
    assert scored.subject_opening_rate == 0.5


def test_identical_openings_score_as_low_variety():
    same = M.score(_payload("The book grew 12.4% on the year overall.",
                            "The book grew 4.0% in the second half of it."))
    assert same.opening_variety == 0.5


def test_a_mechanism_counts_as_causal_and_a_bare_measure_does_not():
    assert M.score(_payload(
        "The increase was led by Cyber, out of a total book movement of $5.3m.")
    ).causal_rate == 1.0
    assert M.score(_payload("Share of wallet rose 0.6pp to 8.9% this year.")
                   ).causal_rate == 0.0


def test_a_so_what_counts_as_an_implication():
    assert M.score(_payload(
        "Closing the 2.4pp gap would add roughly $13.0m of GWP at today's market size.")
    ).implication_rate == 1.0


def test_a_measure_and_a_value_is_a_restatement():
    assert M.score(_payload("Rank within the Marsh book improved 1 place to 4th.")
                   ).restatement_rate == 1.0


def test_a_measure_that_earns_its_place_is_not():
    """The same figure, with the reason behind it, is the sentence we want more of."""
    assert M.score(_payload(
        "Rank improved one place to 4th, and it came at competitors' expense rather "
        "than from a growing pool.")).restatement_rate == 0.0


def test_the_same_bullet_twice_is_counted():
    twice = "Cyber carried the whole of the gain this year."
    assert M.score({"note:1:2:0": twice, "note:3:4:0": twice}).repeated_bullets == 1


# ── the measured before/after ────────────────────────────────────────────────


def test_the_opening_fix_measurably_lowers_the_roll_call():
    """Composed from real facts by the real composers — not a hand-written example."""
    raw = F.points("key_messages", _FACTS)
    before = M.score(_payload(*raw), subject="Zurich")
    after = M.score(_payload(*vary_openings(raw, "Zurich")), subject="Zurich")

    assert before.subject_opening_rate > after.subject_opening_rate
    assert after.subject_opening_rate <= 1.0 / after.bullets + 1e-9, \
        "at most one bullet may still name the carrier"
    assert after.opening_variety >= before.opening_variety
    assert after.bullets == before.bullets, "varying an opening must not drop a claim"


def test_the_score_survives_a_carrier_whose_name_is_a_regex_metacharacter():
    """`MS&AD`, `AXA XL` — subject names go into a pattern, so they must be escaped."""
    scored = M.score(_payload("MS&AD wrote $48.2m with Marsh in 2025 overall."),
                     subject="MS&AD")
    assert scored.subject_opening_rate == 1.0


def test_the_row_renders_every_rate_for_a_run_to_run_comparison():
    row = M.score(_payload("The book grew 12.4% on the year overall."), subject="Z").as_row()
    for field in ("bullets", "subject_openings", "opening_variety", "causal",
                  "implication", "restatement", "repeats"):
        assert field in row


def test_compare_lines_the_two_runs_up():
    a = M.score(_payload("The book grew 12.4% on the year overall."))
    b = M.score(_payload("Cyber carried the gain, so the renewal there is what to protect."))
    rows = dict((name, (x, y)) for name, x, y in M.compare(a, b))
    assert rows["implication_rate"] == (0.0, 1.0)


def test_every_assembled_sub_deck_reports_its_score():
    """A rubric nobody runs is a rubric nobody reads — it goes out with the QA log."""
    import inspect

    from studio.template_fill import assemble

    src = inspect.getsource(assemble._build_subdeck)
    assert "commentary_metrics.log_score(" in src
