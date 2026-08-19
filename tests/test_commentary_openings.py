"""The roll-call, and the two layers that stop it.

Every deterministic composer opens on the subject, because every one is written to stand
alone. Stacked into a column they read as "Zurich wrote …, Zurich ranks …, Zurich grew …" —
which is what a reader recognises as generated before they have read a word of the content.

:mod:`studio.template_fill.openings` fixes the DRAFT (the fallback page), and
``commentary._accept`` refuses an LLM rewrite that reintroduces it. Both are tested here so
the rule is guarded on whichever path a given column ends up taking.

Pure and hermetic: synthetic fact sets, no DB, no LLM.
"""
from __future__ import annotations

import pytest

from studio.template_fill import commentary as CM
from studio.template_fill import feedback as F
from studio.template_fill.openings import subject_openings, vary_openings

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


# ── the draft varies its own openings ────────────────────────────────────────


def test_the_first_bullet_still_names_the_carrier():
    """A column has to say who it is about before it can say 'the book'."""
    said = vary_openings(["Zurich wrote $48.2m with Marsh in 2025.",
                          "Zurich ranks 4th and holds 8.9% of the wallet."], "Zurich")
    assert said[0].startswith("Zurich wrote")


def test_a_second_naming_becomes_the_book():
    said = vary_openings(["Zurich wrote $48.2m with Marsh in 2025.",
                          "Zurich ranks 4th and holds 8.9% of the wallet."], "Zurich")
    assert said[1] == "The book ranks 4th and holds 8.9% of the wallet."


@pytest.mark.parametrize("line,expected", [
    ("Zurich grew its book with Marsh 12.4% year on year to $48.2m.",
     "The book with Marsh grew 12.4% year on year to $48.2m."),
    ("Zurich's book with Marsh fell 4.1% year on year to $30.0m.",
     "The book with Marsh fell 4.1% year on year to $30.0m."),
    ("Zurich held its book with Marsh at $48.2m.",
     "The book with Marsh held at $48.2m."),
    ("Zurich holds 8.9% of the wallet.", "The book holds 8.9% of the wallet."),
])
def test_each_composer_opening_has_a_grammatical_rewrite(line, expected):
    # The first bullet spends the column's one introduction, so `line` is a repeat mention.
    intro = "Zurich wrote $48.2m with Marsh in 2025."
    assert vary_openings([intro, line], "Zurich")[1] == expected


def test_a_shape_with_no_rule_is_left_alone_rather_than_mangled():
    """A slightly repetitive sentence beats an ungrammatical one."""
    odd = "Zurich surprised everybody this year."
    assert vary_openings(["Zurich wrote $48.2m.", odd], "Zurich")[1] == odd


def test_bullets_that_never_named_the_carrier_are_untouched():
    said = ["Cyber carried the whole gain.", "Property gave $1.1m back at renewal."]
    assert vary_openings(said, "Zurich") == said


def test_no_subject_is_not_a_crash():
    said = ["Something happened."]
    assert vary_openings(said, "") == said and vary_openings(said, None) == said


def test_the_figures_are_never_touched():
    """Varying an opening is a grammar edit; it must not move a number."""
    import re

    said = ["Zurich wrote $48.2m with Marsh in 2025.",
            "Zurich ranks 4th and holds 8.9% of the wallet, up 0.6pp."]
    before = re.findall(r"[\d.]+", " ".join(said))
    after = re.findall(r"[\d.]+", " ".join(vary_openings(said, "Zurich")))
    assert before == after


# ── the composers actually produce the roll-call, and the fix lands on them ──


def test_the_key_messages_column_no_longer_opens_every_line_on_the_carrier():
    """The exact complaint: a column of "{carrier} wrote …" / "{carrier} ranks …"."""
    raw = F.points("key_messages", _FACTS)
    assert subject_openings(raw, "Zurich") > 1, "the composers do produce the roll-call"
    assert subject_openings(vary_openings(raw, "Zurich"), "Zurich") == 1


@pytest.mark.parametrize("kind", ["working", "challenges", "growth", "key_messages"])
def test_no_composer_column_names_the_carrier_more_than_once_after_varying(kind):
    varied = vary_openings(F.points(kind, _FACTS), "Zurich")
    assert subject_openings(varied, "Zurich") <= 1


def test_the_feedback_panels_go_through_the_same_fix():
    """The per-country cells are composed by the same functions and had the same problem."""
    text = F._compose("key_messages", _FACTS, 4)
    assert subject_openings(text.split("\n"), "Zurich") <= 1


def test_the_summary_columns_go_through_it_too():
    """`commentary.values` varies AFTER the ledger has chosen, so the surviving bullets
    still carry exactly one introduction between them."""
    import inspect

    src = inspect.getsource(CM.values)
    assert "openings.vary_openings(said, subject)" in src
    assert src.index("ledger.take") < src.index("vary_openings")
