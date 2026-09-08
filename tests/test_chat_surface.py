"""The chat surface: what is laid out where, and what can no longer overlap.

Every check here comes from a reported defect in the chat view:

  * the streaming draft was laid out over the answer above it;
  * the composer floated over the transcript, so a question could end up under
    the status bar with no way to scroll to it;
  * the scope pills sat between the last message and the input, and described
    whichever turn ran last rather than the answer you were reading;
  * the status line traded places between parallel lenses several times a
    second;
  * Custom Peers let a two-carrier "benchmark" through.

These are structural facts (which element contains which, which rule positions
what), so they are checked against the rendered tree and the stylesheet rather
than by eye.

Run:  pytest tests/test_chat_surface.py -q -o pythonpath=.
"""
from __future__ import annotations

import re
from pathlib import Path

from dash.development.base_component import Component

from core.peers import MIN_CUSTOM_PEERS, peer_min_note, peer_shortfall_note, peers_are_enough
from ui.components.chatbot import ai_message, chatbot_page, custom_peers_modal
from ui.progress import STEPS, advance, label_of

STYLE_CSS = Path("assets/style.css").read_text(encoding="utf-8")

SCOPE = [
    {"key": "country", "label": "Country", "value": "Canada",
     "icon": "bi bi-globe2", "source": "asked in this question"},
    {"key": "product", "label": "Product", "value": "Property",
     "icon": "bi bi-box-seam", "source": "asked in this question"},
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


def ids(node) -> set:
    return {n.id for n in walk(node) if isinstance(getattr(n, "id", None), str)}


def classes(node) -> list:
    return [(getattr(n, "className", "") or "") for n in walk(node)]


def find_by_id(node, wanted):
    return next((n for n in walk(node) if getattr(n, "id", None) == wanted), None)


def rule_for(selector: str) -> str:
    """The declaration block of the LAST rule whose selector list opens with it."""
    blocks = re.findall(
        r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", STYLE_CSS
    )
    assert blocks, f"no rule found for {selector}"
    return blocks[-1]


# ── the transcript and the draft share one scroller ─────────────────────────


def test_the_draft_streams_inside_the_scroll_viewport():
    """A sibling of the scroller was laid out over the answer being read."""
    viewport = find_by_id(chatbot_page("jash"), "chat-viewport")
    assert viewport is not None
    assert {"chat-box", "live-draft"} <= ids(viewport)


def test_only_the_viewport_scrolls():
    assert "overflow-y: auto" in rule_for(".chat-viewport")
    assert "overflow" not in rule_for(".chat-bot-text-area")


def test_the_composer_is_laid_out_not_floated_over_the_transcript():
    """`position: fixed/absolute` + a guessed padding is what buried the question."""
    input_area = rule_for(".input-area")
    assert "position:" not in input_area
    assert "flex: 0 0 auto" in input_area
    assert "padding-bottom" not in rule_for(".chat-bot-text-area")


def test_the_viewport_does_not_animate_its_scrolling():
    """A smooth scroll restarted every streaming tick shivers in place."""
    assert not re.search(r"(?m)^\s*scroll-behavior:", rule_for(".chat-viewport"))


# ── scope belongs to the answer ─────────────────────────────────────────────


def test_an_answer_states_the_scope_it_was_built_from():
    message = ai_message("Premium fell.", False, idx=1, scope=SCOPE)
    assert any("answer-scope" in c for c in classes(message))
    values = [
        n.children for n in walk(message)
        if (getattr(n, "className", "") or "") == "scope-pill-value"
    ]
    assert values == ["Canada", "Property"]


def test_an_answer_with_no_scope_shows_no_pills():
    message = ai_message("Hello.", False, idx=1, scope=[])
    assert not any("answer-scope" in c for c in classes(message))


def test_the_scope_bar_no_longer_sits_above_the_composer():
    page = ids(chatbot_page("jash"))
    assert not ({"chat-scope-bar", "chat-scope-pills"} & page)


def test_the_editable_peer_cue_stays_with_the_composer_controls():
    """Scope you can change is a control; scope you can only read is a caption."""
    page = chatbot_page("jash")
    toolbar = next(
        n for n in walk(page)
        if (getattr(n, "className", "") or "") == "composer-toolbar"
    )
    assert {"custom-peers-cue", "boardroom-mode-cue"} <= ids(toolbar)


# ── the status line ─────────────────────────────────────────────────────────


def test_the_status_line_does_not_trade_places_between_lenses():
    line = advance(None, "gpr_agent")
    for node in ("survey_agent", "gpr_agent", "survey_agent"):
        line = advance(line, node)
    assert label_of(line) == STEPS["gpr_agent"].label


def test_the_status_line_still_moves_forward():
    line = advance(None, "context_filler")
    line = advance(line, "gpr_execute_sql")
    line = advance(line, "writer_node")
    assert label_of(line) == STEPS["writer_node"].label


# ── Custom Peers: the same minimum Studio enforces ──────────────────────────


def test_a_peer_set_under_the_minimum_is_not_a_benchmark():
    assert not peers_are_enough(["AIG", "Chubb"])
    assert peers_are_enough(["A", "B", "C", "D", "E"])
    assert peer_min_note(["A"] * MIN_CUSTOM_PEERS) == ""
    assert "3 more to go" in peer_shortfall_note(["A", "B"])


def test_the_dialog_disables_apply_until_the_minimum_is_met():
    from ui.callbacks import toggle_custom_peers_apply

    disabled, _count, note = toggle_custom_peers_apply("Zurich", ["A", "B"])
    assert disabled and note

    disabled, count, note = toggle_custom_peers_apply("Zurich", list("ABCDE"))
    assert not disabled and note == ""
    assert "5 selected" in count


def test_the_dialog_says_the_rule_and_has_somewhere_to_show_it():
    modal = custom_peers_modal()
    assert "custom-peers-min" in ids(modal)
    subtitle = next(
        n for n in walk(modal)
        if (getattr(n, "className", "") or "") == "custom-peers-subtitle"
    )
    assert f"at least {MIN_CUSTOM_PEERS} peers" in subtitle.children
