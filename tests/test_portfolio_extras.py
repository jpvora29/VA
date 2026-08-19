"""The portfolio extras — the deck's answer to "richer, without repeating itself".

The claim ledger keeps a claim off a second page, which on a small pool of claims leaves
later columns thin. These are the extra CLAIMS that fix that: bucketed per column so no two
columns compete for the same material, derived from the one breakdown query the postures
already make, and every one carrying its own figure.
"""
from __future__ import annotations

import pytest

from studio.posture import PostureInput
from studio.template_fill import stance as S


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")


def _book():
    return [
        PostureInput(name="Financial Lines", premium=44e6, pool=414e6, growth_pct=57.1,
                     pool_growth_pct=13.2, rank=3, rank_change=3, share=10.7),
        PostureInput(name="Cyber", premium=44e6, pool=300e6, growth_pct=97.3,
                     pool_growth_pct=13.5, rank=1, rank_change=5, share=14.7),
        PostureInput(name="Property", premium=40e6, pool=545e6, growth_pct=12.1,
                     pool_growth_pct=8.5, rank=6, rank_change=1, share=7.3),
        PostureInput(name="Casualty", premium=37e6, pool=480e6, growth_pct=-0.4,
                     pool_growth_pct=10.2, rank=6, rank_change=0, share=7.6),
        PostureInput(name="Marine", premium=24e6, pool=300e6, growth_pct=12.0,
                     pool_growth_pct=5.4, rank=7, rank_change=-1, share=7.9),
        PostureInput(name="Energy", premium=19e6, pool=253e6, growth_pct=8.9,
                     pool_growth_pct=8.5, rank=7, rank_change=0, share=7.6),
    ]


def _extras():
    return S.PortfolioExtras(
        priorities=tuple(S._product_posture_lines(_book())),
        standing=tuple(S._standing_lines(_book())),
        movement=tuple(S._movement_lines(_book())),
        positioning=tuple(S._positioning_lines(_book())),
        penetration=tuple(S._penetration_lines(_book())),
    )


# ── the buckets do not overlap ───────────────────────────────────────────────


def test_no_two_columns_draw_on_the_same_claim():
    """The whole point of bucketing: a shared pool is drained by whichever column is
    filled first, which is what left the later ones thin."""
    extras = _extras()
    buckets = [extras.priorities, extras.standing, extras.movement,
               extras.positioning, extras.penetration]
    everything = [line for bucket in buckets for line in bucket]
    assert everything, "no extras at all"
    assert len(everything) == len(set(everything)), "two buckets share a line"


def test_every_prose_column_has_material_of_its_own():
    extras = _extras()
    for topic in ("priorities", "thesis", "performance", "reflections", "key_messages"):
        assert extras.for_topic(topic), f"{topic} has no extras"


def test_a_topic_with_no_bucket_gets_nothing():
    assert _extras().for_topic("threats") == ()


# ── every extra carries its figure, and reads as a sentence ──────────────────


@pytest.mark.parametrize("line", [ln for bucket in _extras().__dict__.values() for ln in bucket])
def test_every_extra_is_a_whole_sentence_carrying_a_number(line):
    from studio.template_fill import commentary as CM

    assert line[0].isupper() and line.endswith(".")
    assert any(ch.isdigit() for ch in line), "a claim with no figure behind it"
    assert ": " not in line, "a label, not a sentence"
    assert CM._AI_TELLS.search(line) is None


# ── what each bucket actually claims ─────────────────────────────────────────


def test_standing_counts_the_lines_inside_and_outside_the_top_five():
    said = " ".join(S._standing_lines(_book()))
    assert "inside the top five in 2 of its 6 lines and outside it in 4" in said


def test_standing_names_where_the_book_concentrates():
    assert "42% of everything written" in " ".join(S._standing_lines(_book()))


def test_movement_benchmarks_each_line_against_its_own_pool():
    said = S._movement_lines(_book())
    assert any("Cyber grew 97.3% against a pool at 13.5%" in ln for ln in said)
    assert any("Casualty grew -0.4% against a pool at 10.2%" in ln for ln in said)


def test_positioning_reports_rank_movement_in_both_directions():
    said = " ".join(S._positioning_lines(_book()))
    assert "Rank improved in 3 of 6 lines, furthest in Cyber, up 5 places to #1." in said
    assert "Rank slipped in 1 of 6 lines, furthest in Marine" in said


def test_penetration_names_both_ends_and_what_closing_them_is_worth():
    said = S._penetration_lines(_book())
    assert "deepest in Cyber at 14.7%" in said[0] and "thinnest in Property at 7.3%" in said[0]
    assert "would be worth about" in said[1]


def test_priorities_lead_on_the_management_agenda_order():
    """Defend before scale before fix — the order a leadership team works through."""
    said = S._product_posture_lines(_book())
    assert said[0].startswith("Cyber is the position to defend")
    assert any("Financial Lines is where capacity should go" in ln for ln in said)
    assert any("Casualty needs fixing" in ln for ln in said)


# ── a page that is only one line of the portfolio gets none of this ──────────


def test_a_single_product_scope_has_no_portfolio_to_describe(monkeypatch):
    monkeypatch.setattr(S, "_product_inputs", lambda result: [])
    extras = S.portfolio_extras(object())
    assert extras.for_topic("priorities") == () and extras.for_topic("thesis") == ()


def test_a_failing_breakdown_never_breaks_the_deck(monkeypatch):
    def boom(result):
        raise RuntimeError("warehouse down")

    monkeypatch.setattr(S, "_product_inputs", boom)
    assert S.portfolio_extras(object()).for_topic("thesis") == ()
