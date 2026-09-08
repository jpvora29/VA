"""The answer SHAPE — the thing that stops every answer reading the same.

Every written answer used to arrive as the same five headings whether the
question was "what was Zurich's UK premium?" or "where should we grow?". These
tests pin the replacement: a question picks a shape, the shape picks the
contract, and the contract is what the writer is actually handed.

Run:  pytest tests/test_answer_shape.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.agents.common.answer_shape import (
    DEFAULT_SHAPE,
    SHAPE_KEYS,
    detect_answer_shape,
    get_shape,
    shape_contract,
    shape_label,
)
from core.agents.common.directives import answer_shape, apply_directives
from core.schemas.routing import OutputDirectives, RoutingContext


# ── detection ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question,expected",
    [
        # A lookup wants a number, not an essay.
        ("What was Zurich's premium in the UK in 2024?", "direct"),
        ("How much premium did AXA write in cyber?", "direct"),
        ("How many carriers wrote Property last year?", "direct"),
        # "Why" wants ranked causes.
        ("Why did premium drop in Germany?", "driver"),
        ("What drove the fall in retention?", "driver"),
        ("Explain the decline in our cyber book", "driver"),
        ("What's behind the SoW slip?", "driver"),
        # A league table IS the answer.
        ("Top 5 products by premium", "ranking"),
        ("Which industry is the biggest by premium?", "ranking"),
        ("Rank our product lines by growth", "ranking"),
        # Two subjects side by side.
        ("Compare Chubb vs peers in cyber", "comparison"),
        ("How does Zurich stack up against peers?", "comparison"),
        ("Is AXA ahead of the peer average on SoW?", "comparison"),
        # A series over time.
        ("How has our cyber book grown since 2021?", "trend"),
        ("Show me the premium trend over time", "trend"),
        ("What is the trajectory of NPS?", "trend"),
        # The user asked what to DO.
        ("Where should we grow next year?", "advisory"),
        ("Is it worth exiting property?", "advisory"),
        ("Where is the whitespace in Singapore?", "advisory"),
        # Walking into a meeting.
        ("Brief me on Zurich in the UK", "briefing"),
        ("Where do we stand in Singapore?", "briefing"),
        ("How are we doing this quarter?", "briefing"),
    ],
)
def test_question_picks_its_shape(question, expected):
    assert detect_answer_shape(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Zurich performance in Canada",
        "AXA in the UK market",
        "Cyber premium by industry for Chubb",
        "",
        "   ",
    ],
)
def test_no_opinion_when_nothing_matches(question):
    """None means "no reading" — the caller keeps whatever the LLM said."""
    assert detect_answer_shape(question) is None


def test_why_beats_top_because_it_is_declared_first():
    """Registry order is priority: a "why" about a ranking is a driver question."""
    assert detect_answer_shape("Why is Property top of the list?") == "driver"


def test_advisory_beats_comparison_when_both_appear():
    assert (
        detect_answer_shape("Should we grow cyber compared to property?") == "advisory"
    )


# ── contracts ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", SHAPE_KEYS)
def test_every_shape_has_a_usable_contract(key):
    contract = shape_contract(key)
    assert "[OUTPUT CONTRACT" in contract
    # The rules no shape is allowed to drop, appended once for all of them.
    assert "Peers are ALWAYS aggregated" in contract
    assert "DO NOT SOUND LIKE A TEMPLATE" in contract
    assert shape_label(key)


def test_contracts_actually_differ_from_each_other():
    """The whole point: two shapes must not produce the same instructions."""
    contracts = {key: shape_contract(key) for key in SHAPE_KEYS}
    assert len(set(contracts.values())) == len(SHAPE_KEYS)


def test_direct_forbids_the_furniture_the_full_analysis_asks_for():
    direct = shape_contract("direct")
    full = shape_contract("analyst")
    assert "NO headings" in direct
    assert "NO supporting-data table" in direct
    assert "H3" in full


@pytest.mark.parametrize("key", [None, "", "auto", "not-a-shape"])
def test_unknown_shape_falls_back_to_the_full_analysis(key):
    """A stale checkpoint must never leave a turn with no contract at all."""
    assert get_shape(key).key == DEFAULT_SHAPE
    assert "SHAPE — FULL ANALYSIS" in shape_contract(key)


# ── the per-turn directive ───────────────────────────────────────────────────


def test_apply_directives_records_the_shape():
    directives = OutputDirectives()
    apply_directives("Why did premium fall in Germany?", directives)
    assert directives.shape == "driver"


def test_an_explicit_short_answer_beats_the_inferred_shape():
    """"Briefly, where should we grow?" is one line, not a full advisory."""
    directives = OutputDirectives()
    apply_directives("Briefly, where should we grow?", directives)
    assert directives.depth == "direct"
    assert directives.shape == "direct"


def test_shape_does_not_claim_the_user_stated_a_preference():
    """`source` drives chart-directive telemetry and means "the user asked".

    An inferred shape is not a stated directive, so detecting one must not stamp
    the field or report the turn as having fired a directive.
    """
    directives = OutputDirectives()
    fired = apply_directives("Why did premium fall in Germany?", directives)
    assert fired is False
    assert directives.source == ""
    assert directives.shape == "driver"


def test_a_real_directive_still_stamps_its_source():
    directives = OutputDirectives()
    fired = apply_directives("Why did premium fall, no charts please", directives)
    assert fired is True
    assert directives.source == "deterministic"
    assert directives.charts == "none"
    assert directives.shape == "driver"


# ── reading it back off the turn ─────────────────────────────────────────────


def test_answer_shape_reads_the_routing_context():
    rc = RoutingContext(table_family="premium", intent_type="new_question")
    rc.output_directives.shape = "comparison"
    assert answer_shape(rc) == "comparison"


def test_answer_shape_defaults_when_nothing_was_detected():
    rc = RoutingContext(table_family="premium", intent_type="new_question")
    assert answer_shape(rc) == DEFAULT_SHAPE


def test_answer_shape_survives_a_checkpoint_dict():
    """Deserialized state arrives as plain dicts, not models."""
    assert answer_shape({"output_directives": {"shape": "ranking"}}) == "ranking"


def test_answer_shape_ignores_a_value_it_does_not_know():
    assert answer_shape({"output_directives": {"shape": "freeform"}}) == DEFAULT_SHAPE


def test_explicit_direct_depth_overrides_a_stored_shape():
    rc = RoutingContext(table_family="premium", intent_type="new_question")
    rc.output_directives.shape = "advisory"
    rc.output_directives.depth = "direct"
    assert answer_shape(rc) == "direct"


def test_answer_shape_tolerates_no_context_at_all():
    assert answer_shape(None) == DEFAULT_SHAPE

# ── tables: the shapes ask for them, so the mechanics are pinned ────────────


def test_a_shape_that_asks_for_a_table_gets_the_table_style_guide():
    for key in ("ranking", "comparison", "trend", "analyst", "advisory", "driver"):
        contract = shape_contract(key)
        assert "WHEN YOU WRITE A TABLE" in contract, key
        assert "pipe table" in contract, key
        assert "`---:`" in contract, key


def test_a_shape_that_forbids_a_table_is_not_told_how_to_write_one():
    """Handing table mechanics to a lookup invites a table it must not write."""
    for key in ("direct", "briefing"):
        assert "WHEN YOU WRITE A TABLE" not in shape_contract(key), key


def test_the_table_guide_bans_the_fence_that_stops_a_table_rendering():
    assert "code fence" in shape_contract("ranking")
