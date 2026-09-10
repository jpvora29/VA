"""The commentary acceptance gate repairs a column instead of discarding it.

The bug: `_accept` refused the WHOLE model-written column if any single line was a
fragment, reached for a generated-sounding phrase, opened on the carrier once too
often, or read out a measure and its value. With five such gates over a deck's
worth of columns, no column survived — a build logged

    commentary authorship: 0/27 column(s) written by the model,
    27 kept the deterministic draft

so every page shipped the deterministic draft: the generic, list-like prose the
voice rules, the analyst principles and the ICG glossary all exist to replace.

The bar has not moved — a bad line still never ships. It is applied per LINE.
"""
from __future__ import annotations

import pytest

from studio.template_fill.commentary import (
    _TEMPLATE_OPENERS,
    _accept,
    _keep_lines,
    min_lines,
)
from studio.template_fill.feedback import (
    _CELL_BULLETS,
    _HIGHLIGHT_BULLETS,
    _PANEL_BULLETS,
)


SUBJECT = "Zurich"

GOOD = [
    "The book grew 12% to $12.4M, and that growth sits almost entirely in Property.",
    "Casualty fell away over the same period, which is why rank was flat despite the gain.",
    "Cyber remains thin at under 4% of the book.",
]

# The four habits the per-line rules exist to catch.
READOUT = "The pressure sat in the placement base."
FRAGMENT = "Strong performance in Property"
AI_TELL = "The book grew, demonstrating a robust position in the market."


def _lines(result):
    return (result or "").splitlines()


# ── the fix ──────────────────────────────────────────────────────────────────

def test_a_clean_column_ships_whole():
    assert _lines(_accept(list(GOOD), wanted=3, node="n", subject=SUBJECT)) == GOOD


def test_one_bad_line_costs_that_line_not_the_column():
    """The regression: this used to return None and ship the generic draft."""
    kept = _lines(_accept([*GOOD[:2], READOUT], wanted=3, node="n", subject=SUBJECT))
    assert kept == GOOD[:2]


@pytest.mark.parametrize("bad", [READOUT, FRAGMENT, AI_TELL])
def test_every_line_rule_drops_only_its_own_line(bad):
    kept = _lines(_accept([*GOOD[:2], bad], wanted=3, node="n", subject=SUBJECT))
    assert kept == GOOD[:2]
    assert bad not in kept


def test_a_column_with_too_little_left_keeps_the_draft():
    """The bar still holds: three read-outs are not a column."""
    allbad = [READOUT, "The same book grew with Marsh demand.", FRAGMENT]
    assert _accept(allbad, wanted=3, node="n", subject=SUBJECT) is None


def test_an_over_long_column_is_trimmed_not_refused():
    """The prompt puts lines in priority order, so keep the leading ones."""
    kept = _lines(_accept([*GOOD, "A fourth point that was not asked for and adds little."],
                          wanted=3, node="n", subject=SUBJECT))
    assert kept == GOOD


# ── the subject-opening cap ──────────────────────────────────────────────────

def test_the_carrier_may_open_one_line():
    lines = [f"{SUBJECT} grew its book 12% to $12.4M on the back of Property.", *GOOD[1:]]
    assert len(_lines(_accept(lines, wanted=3, node="n", subject=SUBJECT))) == 3


def test_explicit_carrier_names_are_preserved():
    """Naming the carrier on every line is the roll-call the rule exists to stop."""
    lines = [
        f"{SUBJECT} grew its book 12% to $12.4M on the back of Property.",
        f"{SUBJECT} lost ground in Casualty over the same period, which held rank flat.",
        GOOD[2],
    ]
    kept = _lines(_accept(lines, wanted=3, node="n", subject=SUBJECT))
    assert kept == lines  # Repeating the carrier clarifies whose metrics these are.


# ── _keep_lines reports why ──────────────────────────────────────────────────

def test_drops_are_attributed_so_quality_is_diagnosable():
    kept, dropped = _keep_lines([*GOOD[:1], READOUT, FRAGMENT], SUBJECT)
    assert kept == GOOD[:1]
    assert dropped == {"unclear_comparison": 1, "fragment": 1}


def test_nothing_dropped_reports_nothing():
    kept, dropped = _keep_lines(GOOD, SUBJECT)
    assert kept == GOOD
    assert dropped == {}


# ── how many points a column ships ───────────────────────────────────────────

def test_a_column_is_two_or_three_points():
    """Not four. A fourth point is the weakest claim the composer had, and a
    column padded to length is what makes a page read as generated."""
    assert _PANEL_BULLETS == 3
    assert _CELL_BULLETS == 2, "a table cell keeps the headlines only"
    assert _HIGHLIGHT_BULLETS == 3
    assert min_lines(_PANEL_BULLETS) == 1


def test_two_lines_is_a_whole_column():
    assert _lines(_accept(GOOD[:2], wanted=3, node="n", subject=SUBJECT)) == GOOD[:2]


def test_one_material_line_is_a_whole_column():
    assert _lines(_accept(GOOD[:1], wanted=3, node="n", subject=SUBJECT)) == GOOD[:1]


# ── template openers: the tell a reader names instantly ──────────────────────
#
# Reported: "It won't start with 'The book wants to...' or 'The call is to...'
# or 'The reason is...' — it feels like deterministic commentary." Each of those
# was a fixed template in this package, so every page opened the same way.

TEMPLATE_OPENERS = [
    "The call here is to scale this book, because share of wallet rose.",
    "The call is to defend Property this year.",
    "The book wants to grow in Casualty.",
    "The reason is that Casualty fell away over the period.",
    "What this means is that the book is losing ground.",
    "The takeaway is that Property carried the year.",
]


@pytest.mark.parametrize("line", TEMPLATE_OPENERS)
def test_a_template_opener_is_dropped(line):
    kept, dropped = _keep_lines([line, *GOOD[:2]], SUBJECT)
    assert dropped == {"template_opener": 1}
    assert line not in kept


def test_the_same_words_mid_sentence_are_ordinary_english():
    """Anchored at the start — banning them everywhere would gut good prose."""
    line = "Property carried the year, and the reason is visible in the renewal book."
    kept, _ = _keep_lines([line], SUBJECT)
    assert kept == [line]


def _shape(line: str) -> str:
    """Which stance form produced a line — the join between reason and call."""
    for separator in (", so ", " — ", ", given ", ": ", ". "):
        if separator in line:
            return separator
    return "?"


def test_a_stance_line_no_longer_opens_every_page_the_same_way():
    """A ten-product deck opened ten pages with the same six words.

    The property is that the pages take DIFFERENT SHAPES, not that they start on
    different words: two forms can both begin "The book…" and still read as two
    sentences rather than one template with the numbers swapped.
    """
    from studio.template_fill.stance import _stance_sentence

    books = ["Property", "Casualty", "Cyber", "Marine", "Energy",
             "Financial Lines", "Aviation", "Construction"]
    lines = [_stance_sentence("scale this book", f"share of wallet rose {i}.2 points", b)
             for i, b in enumerate(books)]
    assert len(set(lines)) == len(books), "every page produced an identical line"
    assert len({_shape(ln) for ln in lines}) > 1, "one template served every page"
    assert not any(_TEMPLATE_OPENERS.match(ln) for ln in lines)


def test_a_stance_line_is_the_same_on_every_build():
    """Varied wording must not mean a deck that differs from itself."""
    from studio.template_fill.stance import _stance_sentence

    args = ("scale this book", "share of wallet rose 1.2 points", "Property")
    assert _stance_sentence(*args) == _stance_sentence(*args)


# ── the spare line: why a two-bullet cell no longer fails on one bad line ────
#
# ``COMMENTARY_MODE=ai_required`` stops the build when a field cannot be written, and the
# reported failure was always the same shape: a feedback-table cell (two bullets, so
# ``min_lines`` leaves NO room) lost one line to a gate and took the deck with it. The gate
# now judges every line the model wrote before trimming, and a zero-tolerance column is
# asked for one spare — so a rejected line is covered instead of fatal.


def test_a_two_bullet_cell_accepts_one_supported_finding():
    """The condition the spare exists for. If this changes, the spare is unnecessary."""
    assert min_lines(_CELL_BULLETS) == 1


def test_no_column_is_asked_for_padding():
    from studio.template_fill.commentary import ask_lines

    assert ask_lines(_CELL_BULLETS) == _CELL_BULLETS
    assert ask_lines(1) == 1
    # A column that may already merge or drop has its room; it is not asked for more.
    assert ask_lines(_PANEL_BULLETS) == _PANEL_BULLETS
    assert ask_lines(4) == 4


def test_the_prompt_explicitly_allows_fewer_findings():
    from studio.template_fill.commentary import _bullet_rules

    rules = _bullet_rules(_CELL_BULLETS)
    assert f"one and {_CELL_BULLETS}" in rules
    assert "Do not add filler" in rules


def test_a_spare_covers_a_rejected_line_and_the_cell_still_ships_full():
    """The exact failure: one fragment in a two-bullet cell used to empty the column."""
    kept = _lines(_accept([FRAGMENT, GOOD[0], GOOD[1]], wanted=2, node="n", subject=SUBJECT))
    assert kept == [GOOD[0], GOOD[1]]


def test_the_spare_never_makes_the_cell_longer_than_it_shows():
    kept = _lines(_accept(list(GOOD), wanted=2, node="n", subject=SUBJECT))
    assert len(kept) == 2


def test_two_bad_lines_leave_the_supported_finding():
    """The bar has not moved: the spare covers ONE rejection, not any number."""
    assert _accept([FRAGMENT, READOUT, GOOD[0]], wanted=2, node="n", subject=SUBJECT) == GOOD[0]


def test_lines_are_judged_before_they_are_trimmed():
    """A good line beyond the cell's length is reachable; it used to be cut unseen."""
    lines = [FRAGMENT, GOOD[0], GOOD[1], GOOD[2]]
    assert _lines(_accept(lines, wanted=3, node="n", subject=SUBJECT)) == GOOD
