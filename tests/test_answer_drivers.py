"""Explore drivers, and the shortcuts that get you to a question faster.

Two of the three "wow" items from the roadmap review:

  * §15 contribution analysis — "premium fell $2.7m" becomes "Property is $3.1m
    of that fall, and Cyber offset $0.4m of it", computed from the rows the
    answer was already written from rather than asked of a model;
  * §8A command shortcuts — `/brief`, `/compare`, `/explain` … expanded into
    ordinary questions so they take the normal path.

Run:  pytest tests/test_answer_drivers.py -q -o pythonpath=.
"""
from __future__ import annotations

from dash.development.base_component import Component

from core.agents.common.answer_shape import detect_answer_shape
from core.answers import commands
from core.answers.contribution import decompose
from ui.components.contribution import contribution_panel

TWO_PERIODS = [
    {"Year": "2023", "Product_Line": "Property", "Premium": 11_300_000},
    {"Year": "2023", "Product_Line": "Cyber", "Premium": 1_400_000},
    {"Year": "2023", "Product_Line": "Marine", "Premium": 2_400_000},
    {"Year": "2024", "Product_Line": "Property", "Premium": 8_200_000},
    {"Year": "2024", "Product_Line": "Cyber", "Premium": 1_800_000},
    {"Year": "2024", "Product_Line": "Marine", "Premium": 2_400_000},
]


def walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)


def text_of(node) -> str:
    out = []
    for n in walk(node):
        children = getattr(n, "children", None)
        if isinstance(children, str):
            out.append(children)
    return " ".join(out)


def classes(node) -> list:
    return [(getattr(n, "className", "") or "") for n in walk(node)]


# ── the decomposition ───────────────────────────────────────────────────────


def test_the_movement_is_attributed_to_the_slices_that_caused_it():
    got = decompose(TWO_PERIODS)
    assert got.measure == "Premium" and got.dimension == "Product_Line"
    assert (got.prior_period, got.current_period) == ("2023", "2024")
    assert got.total_move == -2_700_000
    by_name = {d.name: d for d in got.drivers}
    assert by_name["Property"].delta == -3_100_000
    assert by_name["Cyber"].delta == 400_000


def test_the_biggest_mover_leads_whichever_way_it_moved():
    assert [d.name for d in decompose(TWO_PERIODS).drivers] == ["Property", "Cyber", "Marine"]


def test_a_share_over_100_percent_is_reported_not_hidden():
    """One slice falling further than the total means another offset it."""
    payload = decompose(TWO_PERIODS).as_dict()
    shares = {d["name"]: d["share_pct"] for d in payload["drivers"]}
    assert shares["Property"] > 100
    assert shares["Cyber"] < 0


def test_a_measure_column_is_never_chosen_as_the_slice():
    """Splitting premium BY premium attributes the movement to itself."""
    assert decompose(TWO_PERIODS).dimension == "Product_Line"


def test_a_named_measure_wins_over_a_merely_numeric_column():
    rows = [
        {"Year": "2023", "Product_Line": "Property", "Policies": 12, "Premium": 100},
        {"Year": "2024", "Product_Line": "Property", "Policies": 14, "Premium": 130},
        {"Year": "2023", "Product_Line": "Cyber", "Policies": 3, "Premium": 40},
        {"Year": "2024", "Product_Line": "Cyber", "Policies": 4, "Premium": 50},
    ]
    assert decompose(rows).measure == "Premium"


def test_one_period_says_so_instead_of_inventing_a_comparison():
    got = decompose([{"Product_Line": "Property", "Premium": 1}, {"Product_Line": "Cyber", "Premium": 2}])
    assert not got.is_supported
    assert "one period" in got.note


def test_a_period_column_pinned_to_one_value_is_a_filter_not_a_comparison():
    rows = [
        {"Year": "2024", "Product_Line": "Property", "Premium": 1},
        {"Year": "2024", "Product_Line": "Cyber", "Premium": 2},
    ]
    assert not decompose(rows).is_supported


def test_no_dimension_means_the_movement_cannot_be_attributed():
    rows = [{"Year": "2023", "Premium": 10}, {"Year": "2024", "Premium": 8}]
    got = decompose(rows)
    assert not got.is_supported and "dimension" in got.note


def test_no_rows_at_all_says_so():
    assert "no rows" in decompose([]).note.lower()


def test_the_record_survives_the_trip_through_the_store():
    import json

    payload = json.loads(json.dumps(decompose(TWO_PERIODS).as_dict()))
    assert payload["total_move"] == -2_700_000


# ── the panel ───────────────────────────────────────────────────────────────


def test_the_panel_shows_the_totals_and_a_signed_bar_per_slice():
    panel = contribution_panel(decompose(TWO_PERIODS).as_dict())
    shown = text_of(panel)
    assert "What drove the movement" in shown
    assert "Premium by Product Line" in shown and "2023 → 2024" in shown
    bars = [c for c in classes(panel) if c.startswith("contrib-bar-fill")]
    assert len(bars) == 3
    assert any("down" in c for c in bars) and any("up" in c for c in bars)


def test_a_falling_slice_and_a_rising_one_are_told_apart():
    panel = contribution_panel(decompose(TWO_PERIODS).as_dict())
    deltas = [
        (str(n.children), n.className)
        for n in walk(panel)
        if (getattr(n, "className", "") or "").startswith("contrib-delta")
    ]
    assert any("down" in cls and text.startswith("-") for text, cls in deltas)
    assert any("up" in cls and text.startswith("+") for text, cls in deltas)


def test_the_panel_states_why_a_share_can_exceed_100_percent():
    shown = text_of(contribution_panel(decompose(TWO_PERIODS).as_dict()))
    assert "offset by another" in shown


def test_an_unsupported_decomposition_renders_its_reason_not_an_empty_box():
    panel = contribution_panel(decompose([{"Product_Line": "Property", "Premium": 1}]).as_dict())
    assert "one period" in text_of(panel)
    assert any("is-empty" in c for c in classes(panel))


def test_nothing_at_all_renders_nothing():
    assert contribution_panel(None) is None
    assert contribution_panel({}) is None


# ── slash commands ──────────────────────────────────────────────────────────


def test_every_command_expands_into_its_own_answer_shape():
    """The expansion's WORDING is what carries the intent — nothing is plumbed.

    If a template is reworded so its shape no longer detects, the command
    silently starts producing a different kind of answer. This is the test that
    catches that.
    """
    for command in commands.COMMANDS:
        question = command.expand("Zurich in Canada")
        assert detect_answer_shape(question) == command.shape, command.label


def test_a_command_becomes_an_ordinary_question():
    question, shape = commands.expand("/brief Zurich in Canada")
    assert question.startswith("Brief me on Zurich in Canada")
    assert shape == "briefing"


def test_a_normal_question_passes_through_untouched():
    assert commands.expand("what was premium in 2024?") == ("what was premium in 2024?", "")


def test_a_slash_inside_a_question_is_not_a_command():
    text = "premium w/ Zurich"
    assert commands.expand(text) == (text, "")


def test_an_unknown_command_is_left_alone_rather_than_guessed_at():
    assert commands.expand("/nope hello") == ("/nope hello", "")


def test_a_command_with_no_subject_still_expands():
    """Legitimate when the conversation already has scope to inherit."""
    question, shape = commands.expand("/whitespace")
    assert question and shape == "advisory"


# ── the menu ────────────────────────────────────────────────────────────────


def test_the_menu_lists_every_command_on_a_bare_slash():
    assert [c.name for c in commands.suggestions("/")] == [c.name for c in commands.COMMANDS]


def test_the_menu_narrows_as_you_type():
    assert [c.name for c in commands.suggestions("/co")] == ["compare"]


def test_the_menu_gets_out_of_the_way_once_a_subject_is_being_typed():
    assert [c.name for c in commands.suggestions("/brief Zur")] == ["brief"]


def test_the_menu_never_appears_over_a_normal_question():
    assert commands.suggestions("what was premium") == ()
    assert commands.suggestions("") == ()

# ── through the real callbacks ──────────────────────────────────────────────


def transcript() -> dict:
    return {
        "thread_id": "t1",
        "awaiting_clarification": False,
        "messages": [
            {"type": "HumanMessage", "content": "why did premium fall?"},
            {"type": "AIMessage", "content": "Premium fell $2.7m.", "question": "why did premium fall?"},
            {"type": "Evidence", "views": [{"rows": TWO_PERIODS, "chart_data": {}, "lens": "premium"}]},
        ],
    }


def test_the_rows_behind_an_answer_are_found_in_the_evidence_message():
    """`_rows_for_answer` reads the panel's views — Export and the decomposition
    both depend on it, and the old single-list shape no longer arrives."""
    from ui.callbacks import _rows_for_answer

    assert len(_rows_for_answer(transcript(), 1)) == len(TWO_PERIODS)


def test_exploring_drivers_computes_instead_of_asking_when_it_can(monkeypatch):
    """No model call, no second query — and it cannot disagree with the answer."""
    import ui.callbacks as cb

    history = transcript()
    monkeypatch.setattr(
        cb, "ctx",
        type("C", (), {"triggered_id": {"type": "answer-action", "idx": 1, "action": "drivers"},
                       "triggered": [{"value": 1}]})(),
    )
    updated, trigger, thinking, board = cb.ask_from_answer([1], [None], history)
    assert trigger is cb.no_update, "a computed decomposition must not spend a turn"
    # It lands ON the answer, not as a message after it: the decomposition is
    # part of that finding, and appending it would put it below the evidence
    # card it explains.
    answer = updated["messages"][1]
    assert answer["type"] == "AIMessage"
    assert answer["contribution"]["total_move"] == -2_700_000


def test_it_falls_back_to_asking_when_the_rows_cannot_support_it(monkeypatch):
    import ui.callbacks as cb

    history = transcript()
    history["messages"][2] = {
        "type": "Evidence",
        "views": [{"rows": [{"Product_Line": "Property", "Premium": 1}], "chart_data": {}}],
    }
    monkeypatch.setattr(
        cb, "ctx",
        type("C", (), {"triggered_id": {"type": "answer-action", "idx": 1, "action": "drivers"},
                       "triggered": [{"value": 1}]})(),
    )
    updated, trigger, _thinking, _board = cb.ask_from_answer([1], [None], history)
    assert trigger is True, "with no decomposition available, ask the model"
    assert updated["messages"][-1]["type"] == "HumanMessage"

def test_the_answer_its_evidence_and_its_drivers_are_one_card():
    """A chart in a card of its own, at a different width, read as broken."""
    from ui.callbacks import render_chat

    history = transcript()
    history["messages"][1]["contribution"] = decompose(TWO_PERIODS).as_dict()
    items = render_chat(history, False, False, None, {})
    assert len(items) == 2, "the user turn and ONE answer card"
    card = items[-1]
    rendered = classes(card)
    assert "has-evidence" in card.className
    assert any("ev-panel" in c for c in rendered)
    assert any("contrib-panel" in c for c in rendered)

