"""The ICG glossary — the definitions commentary is held to, and the units it is said in.

``core/data/valid_values.py`` defines columns. ``core/definitions/terms.yaml`` defines the
derived business concepts an analyst reasons in, and every one of them carries the specific
overstatement it attracts. That ``never`` field is the reason the file exists, so it is the
thing most heavily guarded here.

Pure and hermetic: no DB, no LLM.
"""
from __future__ import annotations

import pytest

from core.definitions import Term, get_glossary, load_glossary
from studio.template_fill import units as U


@pytest.fixture(scope="module")
def glossary():
    return get_glossary()


# ── the file itself has to be usable ─────────────────────────────────────────


def test_the_shipped_glossary_validates(glossary):
    """The CI guard: a term without a definition, a ban, or with a bogus unit."""
    assert glossary.validate() == []


def test_every_term_the_commentary_leans_on_is_defined(glossary):
    """These are the concepts the composers and the evidence pack actually emit. A term
    the pack cites but the glossary does not define reaches the model undefended."""
    for key in ("premium", "marsh_book", "share_of_wallet", "share_of_portfolio", "rank",
                "peer_average", "headroom", "whitespace", "appetite", "capture_rate",
                "percentage_point", "survey_score", "yoy"):
        assert glossary.get(key) is not None, f"{key} is not defined"


@pytest.mark.parametrize("alias,expected", [
    ("sow", "share_of_wallet"),
    ("wallet share", "share_of_wallet"),
    ("gwp", "premium"),
    ("pp", "percentage_point"),
    ("peer benchmark", "peer_average"),
    ("Share of Wallet", "share_of_wallet"),      # label, and case-insensitively
])
def test_a_term_resolves_from_the_names_people_actually_use(glossary, alias, expected):
    assert glossary.get(alias).key == expected


def test_an_unknown_name_is_none_rather_than_a_crash(glossary):
    assert glossary.get("combined ratio") is None and glossary.get("") is None


# ── the distinctions the deck keeps getting wrong ────────────────────────────


def test_share_of_wallet_is_banned_from_becoming_market_share(glossary):
    never = glossary.get("share_of_wallet").never.lower()
    assert "market share" in never


def test_rank_is_banned_from_becoming_market_rank(glossary):
    never = glossary.get("rank").never.lower()
    assert "market rank" in never and "market leader" in never


def test_headroom_is_banned_from_becoming_addressable_market(glossary):
    assert "addressable" in glossary.get("headroom").never.lower()


def test_share_of_wallet_and_share_of_portfolio_are_separate_terms(glossary):
    """Different denominators, indistinguishable from the number alone — which is why the
    deck must never put them in one clause."""
    sow, sop = glossary.get("share_of_wallet"), glossary.get("share_of_portfolio")
    assert sow.key != sop.key
    assert "marsh book" in sow.definition.lower()
    assert "own" in sop.definition.lower()


def test_appetite_is_marked_as_something_the_data_cannot_show(glossary):
    """The distinction the writer needs most: premium shows what was WRITTEN, never why
    it was not. A model that cannot tell computed from uncomputable infers the rest."""
    appetite = glossary.get("appetite")
    assert not appetite.is_computed
    assert "never infer appetite from premium" in appetite.never.lower()


def test_a_computed_term_carries_the_formula_this_system_uses(glossary):
    sow = glossary.get("share_of_wallet")
    assert sow.is_computed and "marsh book" in sow.formula.lower()


# ── the prompt block ─────────────────────────────────────────────────────────


def test_a_brief_carries_the_definition_and_the_ban(glossary):
    brief = glossary.brief(["rank"])
    assert "within the Marsh book" in brief.lower() or "marsh book" in brief.lower()
    assert "NEVER:" in brief and "market rank" in brief


def test_a_brief_names_an_uncomputed_term_as_uncomputed(glossary):
    assert "NOT computed from our data." in glossary.brief(["appetite"])


def test_a_brief_of_nothing_is_empty_rather_than_everything(glossary):
    """The writer asks for the terms its evidence uses. An empty ask is a page with no
    terms in play, not an invitation to paste the whole glossary into the prompt."""
    assert glossary.brief(["not_a_term"]) == ""


def test_an_unknown_name_in_a_brief_is_skipped_not_raised(glossary):
    """A typo in a caller's term list must not be able to break deck generation."""
    brief = glossary.brief(["rank", "not_a_term"])
    assert "NEVER:" in brief


def test_a_brief_does_not_repeat_a_term_reached_by_two_names(glossary):
    assert glossary.brief(["sow", "share_of_wallet"]).count("NEVER:") == 1


# ── a broken file degrades, it does not explode ──────────────────────────────


def test_an_unreadable_glossary_yields_an_empty_one(tmp_path):
    """Definitions sharpen commentary; they do not gate it. A deck still builds."""
    broken = tmp_path / "terms.yaml"
    broken.write_text("this: [is: not: valid: yaml", encoding="utf-8")
    assert load_glossary(broken).terms == ()


def test_a_missing_glossary_yields_an_empty_one(tmp_path):
    assert load_glossary(tmp_path / "absent.yaml").brief(["rank"]) == ""


# ── percentage points, spelled out ───────────────────────────────────────────
#
# "pp" was in fourteen places and reached carrier executives as "share rose 1.3pp" — an
# abbreviation half the room reads as "percent", which is a different and wrong claim.


@pytest.mark.parametrize("value,expected", [
    (1.3, "1.3 percentage points"),
    (-1.7, "1.7 percentage points"),        # magnitude only; direction is the verb's job
    (1.0, "1.0 percentage point"),          # singular, so it reads aloud
    (0.0, "0.0 percentage points"),
])
def test_points_are_spelled_out(value, expected):
    assert U.points(value) == expected


@pytest.mark.parametrize("value,expected", [
    (1.3, "1.3 points of share"),
    (1.0, "1.0 point of share"),
])
def test_the_short_form_is_for_a_sentence_that_already_said_share(value, expected):
    assert U.points_of_share(value) == expected


def test_no_value_renders_as_nothing_rather_than_none(value=None):
    assert U.points(value) == "" and U.points_of_share(value) == ""


@pytest.mark.parametrize("value,flat", [(None, True), (0.0, True), (0.04, True), (0.05, False)])
def test_a_movement_too_small_to_matter_is_flat(value, flat):
    assert U.is_flat(value) is flat


def test_the_composers_no_longer_abbreviate_it():
    """The regression that started this: `f"{x:.1f}pp"` in fourteen places."""
    import re
    from pathlib import Path

    abbreviated = re.compile(r"\}pp\b|\dpp\b")
    for path in (Path("studio/template_fill/feedback.py"), Path("studio/posture.py")):
        assert not abbreviated.search(path.read_text(encoding="utf-8")), path
