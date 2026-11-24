"""Answer card v5: the fixes behind the chat redesign mock-up.

- every answer gets a Summary, even when the writer opens with a heading or a bullet;
- figures are never drawn underlined (no highlighter on bold, no dead links);
- the writer is told to open with one plain conclusion sentence;
- the card renders through the real `ai_message` with the summary in place.
"""

from __future__ import annotations

from pathlib import Path

from core.agents.common.answer_shape import SHAPE_KEYS, shape_contract
from ui.components.answer_lead import lift_lead, split_lead
from ui.components.deltas import mark_deltas, mark_line, unlink

ASSETS = Path(__file__).resolve().parents[1] / "assets"


# --------------------------------------------------------------------------- #
# The summary is always there
# --------------------------------------------------------------------------- #


def test_plain_prose_keeps_the_existing_split():
    source = "Premium grew 12% to $4.2M. Property led.\n\n### Drivers\n- a"
    assert lift_lead(source) == split_lead(source)


def test_a_summary_heading_gives_up_its_sentence_and_disappears():
    lead = lift_lead(
        "### Executive summary\nPremium grew 18% to $10.0M in 2025. Property led."
        "\n\n### Drivers\n- Property added $0.8M"
    )
    assert lead.headline == "Premium grew 18% to $10.0M in 2025."
    assert lead.standfirst == "Property led."
    assert lead.body == "### Drivers\n- Property added $0.8M"


def test_a_section_heading_stays_while_something_is_still_under_it():
    lead = lift_lead(
        "### Performance\nPremium grew 18% to $10.0M in 2025.\n\nMarine fell.\n\n### Drivers"
    )
    assert lead.headline == "Premium grew 18% to $10.0M in 2025."
    assert lead.body.startswith("### Performance\nMarine fell.")


def test_a_heading_left_with_nothing_under_it_is_dropped():
    lead = lift_lead("### Performance\nPremium grew 18% to $10.0M.\n\n### Drivers\n- a")
    assert lead.body == "### Drivers\n- a"


def test_an_opening_bullet_becomes_the_summary_and_leaves_the_list():
    lead = lift_lead("- Premium grew 18% to $10.0M in 2025.\n- Marine fell 33%")
    assert lead.headline == "Premium grew 18% to $10.0M in 2025."
    assert lead.body == "- Marine fell 33%"


def test_a_table_first_answer_still_has_no_invented_summary():
    source = "| a | b |\n| - | - |"
    assert lift_lead(source).headline == ""
    assert lift_lead(source).body == source


def test_a_fragment_is_not_promoted():
    assert lift_lead("- Yes.\n- No.").headline == ""


# --------------------------------------------------------------------------- #
# Figures are never underlined
# --------------------------------------------------------------------------- #


def test_a_link_that_leads_nowhere_keeps_only_its_text():
    assert unlink("Premium hit [**$4.2M**](#f3).") == "Premium hit **$4.2M**."
    assert unlink("[$40M](fact:m1)") == "$40M"


def test_a_real_web_link_is_kept():
    assert (
        unlink("see [docs](https://example.com)") == "see [docs](https://example.com)"
    )


def test_marking_changes_also_drops_dead_links():
    assert "](" not in mark_line("up [+18.0%](#c1)")
    assert mark_deltas("- Marine fell to [$40M](fact:m1)") == "- Marine fell to $40M"


def test_bold_answer_text_has_no_highlighter_band():
    """The red band under bold text read as a random underline on the numbers."""
    style = (ASSETS / "style.css").read_text(encoding="utf-8")
    block = style.split(".insight-card-body strong {", 1)[1].split("}", 1)[0]
    assert "background" not in block


def test_direction_reads_green_up_red_down_on_the_card():
    layer = (ASSETS / "va_shell_chat_v3.css").read_text(encoding="utf-8")
    assert "--va-up: #15803d" in layer and "--va-down: #c62828" in layer
    assert ".delta.delta-up { color: var(--va-up)" in layer


# --------------------------------------------------------------------------- #
# The writer is asked for the shape the card needs
# --------------------------------------------------------------------------- #


def test_every_shape_asks_for_a_plain_conclusion_first():
    for key in SHAPE_KEYS:
        contract = shape_contract(key)
        assert "[FIRST LINE AND FIGURES]" in contract, key
        assert "Never put a figure inside a link" in contract, key


# --------------------------------------------------------------------------- #
# End to end: the real card component
# --------------------------------------------------------------------------- #


def _texts(component) -> list[tuple[str, str]]:
    """(className, text) for every node with text, depth first."""
    found = []
    children = getattr(component, "children", None)
    class_name = str(getattr(component, "className", "") or "")
    if isinstance(children, str):
        found.append((class_name, children))
    for child in children if isinstance(children, list | tuple) else [children]:
        if child is not None and not isinstance(child, str):
            found.extend(_texts(child))
    return found


def test_a_heading_first_answer_renders_with_a_summary():
    from ui.components.chatbot import ai_message

    content = (
        "### Executive summary\nGENERALI's premium grew 18.0% to $11.8M in 2025.\n\n"
        "### Property is the growth engine\n- Property added $0.8M"
    )
    card = ai_message(content, is_insight=True, idx=0, question="q", route="premium")
    texts = _texts(card)
    assert ("answer-summary-label", "Summary") in texts
    markdown = [
        getattr(node, "children", "")
        for node in _walk(card)
        if type(node).__name__ == "Markdown"
    ]
    assert any("grew 18.0% to $11.8M" in str(text) for text in markdown[:1])
    # Moved, not copied: the sentence appears once on the card.
    assert sum("grew 18.0% to $11.8M" in str(text) for text in markdown) == 1


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    for child in children if isinstance(children, list | tuple) else [children]:
        if child is not None and not isinstance(child, str):
            yield from _walk(child)
