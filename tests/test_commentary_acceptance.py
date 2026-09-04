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
READOUT = "Rank improved to 4th."
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
    allbad = [READOUT, "Share of wallet rose 0.6pp.", "Premium up 4%."]
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


def test_a_roll_call_loses_its_later_lines_not_the_column():
    """Naming the carrier on every line is the roll-call the rule exists to stop."""
    lines = [
        f"{SUBJECT} grew its book 12% to $12.4M on the back of Property.",
        f"{SUBJECT} lost ground in Casualty over the same period, which held rank flat.",
        GOOD[2],
    ]
    kept = _lines(_accept(lines, wanted=3, node="n", subject=SUBJECT))
    assert len(kept) == 2
    assert kept[0].startswith(SUBJECT)
    assert not kept[1].startswith(SUBJECT)


# ── _keep_lines reports why ──────────────────────────────────────────────────

def test_drops_are_attributed_so_quality_is_diagnosable():
    kept, dropped = _keep_lines([*GOOD[:1], READOUT, FRAGMENT], SUBJECT)
    assert kept == GOOD[:1]
    assert dropped == {"metric_readout": 1, "fragment": 1}


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
    assert min_lines(_PANEL_BULLETS) == 2


def test_two_lines_is_a_whole_column():
    assert _lines(_accept(GOOD[:2], wanted=3, node="n", subject=SUBJECT)) == GOOD[:2]


def test_one_line_is_not():
    assert _accept(GOOD[:1], wanted=3, node="n", subject=SUBJECT) is None


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
