"""The Prism conversation surface: what an answer states, and where it states it.

Every check here is one of the reported UX defects, pinned so it cannot come
back:

  * the greeting filled the first screen, so the composer — the only thing on
    that screen you can act on — was the last thing you reached;
  * the analytical tools sat behind an unlabelled "+", and the peer set the
    benchmarks were computed against was never stated at all;
  * a chart scrolled away the moment you asked about it;
  * an answer buried its conclusion inside a paragraph, and buried the dataset
    it came from inside a closed drawer;
  * four equal-weight buttons under every answer said nothing about which one
    the answer was for;
  * under the desktop breakpoint the rail stayed a column and the content ran
    off the left edge.

Structural facts, so they are checked against the rendered tree and the
stylesheets rather than by eye.

Run:  pytest tests/test_chat_prism_surface.py -q -o pythonpath=.
"""
from __future__ import annotations

import re
from pathlib import Path

from dash.development.base_component import Component

from ui.analysis import dock_target
from ui.components.analysis_dock import DOCK_NS, dock_body
from ui.components.answer_actions import (
    ACTIONS,
    AnswerContext,
    actions_for,
    answer_footer,
    promoted_action,
)
from ui.components.answer_lead import key_figures, split_lead
from ui.components.chatbot import ai_message, chatbot_page, custom_peers_cue, welcome_hero
from ui.components.provenance import dataset_label, provenance_drawer
from ui.components.turn import format_stamp

CHAT_CSS = Path("assets/va_shell_chat.css").read_text(encoding="utf-8")
SHELL_CSS = Path("assets/va_shell.css").read_text(encoding="utf-8")

CONTRIBUTION = {
    "measure": "premium",
    "dimension": "product_line",
    "prior_period": "Q2 2025",
    "current_period": "Q2 2026",
    "prior_total": 100_000_000.0,
    "current_total": 112_000_000.0,
    "total_move": 12_000_000.0,
    "drivers": [
        {"name": "Property", "prior": 50e6, "current": 56e6, "delta": 6e6},
        {"name": "Casualty", "prior": 34e6, "current": 38e6, "delta": 4e6},
        {"name": "Specialty", "prior": 16e6, "current": 18e6, "delta": 2e6},
    ],
}

PROVENANCE = {
    "state": "verified",
    "question": "What drove premium growth in Q2?",
    "queries": [
        {
            "table": "fact_premium",
            "sql": "SELECT product_line, SUM(premium) FROM fact_premium GROUP BY 1",
            "rows": [{"product_line": "Property", "premium": 56}],
        }
    ],
}

SCOPE = [
    {"key": "carrier", "label": "Carrier", "value": "Zurich",
     "icon": "bi bi-building", "source": "asked in this question"},
    {"key": "year", "label": "Period", "value": "Q2 2026",
     "icon": "bi bi-calendar3", "source": "asked in this question"},
]


# ── helpers ──────────────────────────────────────────────────────────────────


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


def texts(node, class_name: str) -> list:
    return [
        n.children
        for n in walk(node)
        if (getattr(n, "className", "") or "") == class_name
    ]


def rule_for(css: str, selector: str) -> str:
    blocks = re.findall(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert blocks, f"no rule found for {selector}"
    return blocks[-1]


# ── the finding, pulled to the front ─────────────────────────────────────────


def test_the_conclusion_is_set_as_the_conclusion():
    lead = split_lead("Premium grew 12%. Property led the increase.\n\nThe rest.")
    assert lead.headline == "Premium grew 12%."
    assert lead.standfirst == "Property led the increase."
    assert lead.body == "The rest."


def test_promoting_the_lead_never_loses_a_word():
    """Typography, not summarisation: the three parts put the answer back."""
    source = "Premium grew 12%. Property led it.\n\n### Detail\n- one\n- two"
    lead = split_lead(source)
    rebuilt = f"{lead.headline} {lead.standfirst}\n\n{lead.body}"
    assert rebuilt == source


def test_a_structured_answer_keeps_the_structure_its_writer_chose():
    for source in (
        "### Executive summary\nPremium grew.",
        "- Premium grew 12%\n- Property led",
        "| a | b |\n| - | - |",
    ):
        assert split_lead(source) .headline == ""
        assert split_lead(source).body == source


def test_a_paragraph_wearing_a_full_stop_is_not_a_headline():
    """Past ~190 characters, setting the first sentence large hurts the read."""
    long_first = "Premium " + "grew and grew " * 20 + "in Q2. Then it stopped."
    assert split_lead(long_first).headline == ""


def test_a_decimal_point_does_not_end_a_sentence():
    lead = split_lead("Premium reached $112.4M in Q2. Property led it.")
    assert lead.headline == "Premium reached $112.4M in Q2."


def test_the_key_figures_come_from_the_same_totals_as_the_bars():
    figures = key_figures(CONTRIBUTION)
    assert [f.value for f in figures] == ["$112.0m", "+12%"]
    assert figures[0].label == "Premium (Q2 2026)"
    assert figures[1].label == "Change vs Q2 2025"


def test_an_answer_with_no_decomposition_invents_no_figures():
    assert key_figures(None) == []
    assert key_figures({"drivers": [], "note": "nothing to decompose"}) == []


# ── what the answer states about itself ──────────────────────────────────────


def test_an_answer_names_who_wrote_it_and_when():
    message = ai_message(
        "Premium grew 12%. Property led it.", True, idx=1,
        shape="analyst", ts="2026-09-09T16:14:00", source="Premium",
    )
    assert texts(message, "turn-name") == ["Virtual Analyst"]
    assert texts(message, "turn-stamp") == ["9 Sep 2026, 4:14 PM"]


def test_a_transcript_saved_before_stamping_renders_without_a_time():
    """An unstamped answer must not be labelled with the time it was reopened."""
    message = ai_message("Premium grew.", False, idx=1)
    assert texts(message, "turn-stamp") == []
    assert format_stamp("") == ""


def test_the_dataset_is_readable_without_opening_the_drawer():
    drawer = provenance_drawer(PROVENANCE, period="Q2 2026")
    chip = texts(drawer, "prov-dataset")
    assert chip and "Q2 2026" in chip[0][1].children
    assert texts(drawer, "prov-summary-text") == ["Source & calculation"]


def test_the_dataset_chip_is_named_in_business_words_not_schema_ones():
    assert "fact_" not in dataset_label(PROVENANCE)
    assert dataset_label(PROVENANCE, "Q2 2026").endswith("Q2 2026")


def test_the_answer_states_the_period_it_ran_under_on_its_source_line():
    message = ai_message(
        "Premium grew 12%. Property led it.", True, idx=1, shape="analyst",
        scope=SCOPE, provenance=PROVENANCE,
    )
    assert any("prov-dataset" in c for c in classes(message))


# ── one promoted action ──────────────────────────────────────────────────────


def test_exactly_one_action_is_promoted():
    ctx = AnswerContext(idx=1, shape="analyst", has_rows=True)
    footer = answer_footer(ctx, content="x")
    primary = [c for c in classes(footer) if "answer-action-btn is-primary" in c]
    assert len(primary) == 1


def test_the_promoted_action_is_one_this_answer_can_actually_take():
    """Promoting a step the answer cannot run is worse than promoting none."""
    lookup = AnswerContext(idx=0, shape="direct", has_rows=True)
    assert promoted_action(actions_for(lookup)).key == "export"

    bare = AnswerContext(idx=0, shape="direct")
    assert promoted_action(actions_for(bare)) is None
    assert "is-primary" not in " ".join(classes(answer_footer(bare, content="x")))


def test_the_promoted_action_is_drawn_first():
    ctx = AnswerContext(idx=1, shape="analyst", has_rows=True)
    keys = [
        c["action"]
        for c in (getattr(n, "id", None) for n in walk(answer_footer(ctx, content="x")))
        if isinstance(c, dict) and c.get("type") == "answer-action"
    ]
    assert keys[0] == "decision"
    assert set(keys) == {a.key for a in ACTIONS}


def test_only_one_next_question_rides_on_the_card():
    message = ai_message(
        "Premium grew 12%. Property led it.", True, idx=1, shape="analyst",
        followup="Compare with peers",
    )
    chips = [
        n for n in walk(message)
        if (getattr(n, "className", "") or "") == "answer-next-chip"
    ]
    assert len(chips) == 1
    assert chips[0].id["q"] == "Compare with peers"


# ── the analysis panel ───────────────────────────────────────────────────────


def _history(**answer):
    base = {"type": "AIMessage", "content": "Premium grew.", "question": "Why?"}
    base.update(answer)
    return {"messages": [{"type": "HumanMessage", "content": "Why?"}, base]}


def test_the_panel_follows_the_newest_answer_that_produced_evidence():
    history = _history(contribution=CONTRIBUTION)
    target = dock_target(history, None)
    assert target is not None and target.idx == 1 and not target.pinned


def test_an_answer_with_no_evidence_does_not_become_the_panels_subject():
    assert dock_target(_history(), None) is None
    assert dock_target({"messages": []}, None) is None


def test_a_pin_holds_the_panel_on_one_answer():
    history = _history(contribution=CONTRIBUTION)
    target = dock_target(history, 1)
    assert target is not None and target.pinned


def test_a_stale_pin_falls_back_rather_than_emptying_the_panel():
    """A pin left pointing at a conversation that has been replaced."""
    history = _history(contribution=CONTRIBUTION)
    target = dock_target(history, 47)
    assert target is not None and not target.pinned


def test_the_panel_and_the_card_cannot_collide_over_an_id():
    """The same evidence renders twice on one page, so the ids must not clash.

    Two result sets, because a single view needs no tabs and would mint no id at
    all — and it is exactly the tabs and the Chart/Data switches that a duplicate
    would break, by handing one MATCH callback two components to answer for.
    """
    history = _history()
    history["messages"].append(
        {"type": "Evidence", "views": [
            {"rows": [{"product_line": "Property", "premium": 56}]},
            {"rows": [{"country": "Canada", "premium": 41}]},
        ]}
    )
    target = dock_target(history, None)
    assert target is not None and len(target.views) == 2

    dock_ids = [
        getattr(n, "id", None) for n in walk(dock_body(target))
        if isinstance(getattr(n, "id", None), dict)
    ]
    assert dock_ids, "the panel rendered nothing with an id"
    assert all(str(i.get("idx", "")).startswith(DOCK_NS) for i in dock_ids)

    # …and the transcript's copy of the same evidence keeps plain integer ids.
    card = ai_message(
        "Premium grew 12%. Property led it.", True, idx=1, shape="analyst",
        evidence=target.views, pane_ids=[0, 1],
    )
    card_ids = [
        n.id for n in walk(card)
        if isinstance(getattr(n, "id", None), dict) and "idx" in n.id
    ]
    assert card_ids and not any(
        str(i["idx"]).startswith(DOCK_NS) for i in card_ids
    )


def test_the_panel_says_whether_it_is_following_or_held():
    following = dock_body(dock_target(_history(contribution=CONTRIBUTION), None))
    assert "Latest" in str(following)
    held = dock_body(dock_target(_history(contribution=CONTRIBUTION), 1))
    assert "analysis-unpin" in ids(held)


def test_an_answer_with_evidence_offers_the_pin_and_a_bare_one_does_not():
    with_evidence = ai_message(
        "Premium grew 12%. Property led it.", True, idx=1, shape="analyst",
        contribution=CONTRIBUTION,
    )
    pins = [
        n for n in walk(with_evidence)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "answer-pin"
    ]
    assert len(pins) == 1

    bare = ai_message("Premium grew.", False, idx=1)
    assert not [
        n for n in walk(bare)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "answer-pin"
    ]


def test_the_chat_page_mounts_both_columns_and_the_switch_between_them():
    page = chatbot_page("jash")
    assert {"analysis-dock", "analysis-dock-body", "chat-workspace",
            "chat-view-switch", "analysis-pin", "analysis-view"} <= ids(page)


def narrow_block(css: str, width: int) -> str:
    """The declarations inside one max-width media query."""
    match = re.search(
        r"@media \(max-width: " + str(width) + r"px\) \{(.*?)\n\}\n", css, re.S
    )
    assert match, f"no {width}px breakpoint"
    return match.group(1)


def test_neither_column_is_unmounted_when_the_other_is_showing():
    """Hidden, not unmounted — a switch that unmounts loses every chart, every
    open drawer and the half-typed question."""
    block = narrow_block(CHAT_CSS, 1024)
    assert ".chat-workspace.show-chat .analysis-dock { display: none; }" in block
    # The Analysis view hides the TRANSCRIPT, not the whole column: the chart is
    # usually what prompts the next question, so the composer stays put.
    assert ".chat-workspace.show-analysis .chat-row { display: none; }" in block
    assert ".chat-workspace.show-analysis .chat-column { display: none; }" not in block


# ── the composer names what it does ──────────────────────────────────────────


def test_the_tools_menu_is_labelled():
    page = chatbot_page("jash")
    menu = next(n for n in walk(page) if getattr(n, "id", None) == "composer-add-menu")
    assert "Tools" in str(menu.label)
    assert menu.toggleClassName == "composer-tool-btn"
    assert {"menu-pitch-builder", "menu-boardroom-mode", "menu-custom-peers"} <= ids(menu)


def test_the_peer_set_is_stated_even_when_it_is_the_default():
    """A benchmark whose comparison set is invisible is a number you cannot check."""
    default = custom_peers_cue(None)
    assert default is not None
    assert "Default" in str(default)
    assert "custom-peers-edit" in ids(default)
    # Nothing to clear, so no clear button.
    assert "custom-peers-clear" not in ids(default)


def test_a_pinned_peer_set_says_how_many_and_for_whom():
    cue = custom_peers_cue({"carrier": "Zurich", "peers": list("ABCDE"), "flow": "gpr"})
    assert "5 custom · Zurich" in str(cue)
    assert "custom-peers-clear" in ids(cue)


# ── the first question is the point of the first screen ──────────────────────


def test_the_greeting_does_not_fill_the_screen():
    """The badge, the display-size greeting and the three-line blurb are gone."""
    hero = welcome_hero("Jash")
    assert not any("welcome-badge" in c for c in classes(hero))
    title = rule_for(CHAT_CSS, ".welcome-title")
    largest = float(re.search(r"clamp\([^,]+,[^,]+,\s*([\d.]+)px\)", title).group(1))
    assert largest <= 28, f"the greeting is still {largest}px"


def test_the_starters_are_outcomes_and_they_load_rather_than_send():
    hero = welcome_hero("Jash")
    outcomes = texts(hero, "starter-chip-outcome")
    assert outcomes == ["Share of wallet", "Explain premium growth",
                        "Compare peers", "Explore market rates"]
    kinds = {
        n.id["type"] for n in walk(hero)
        if isinstance(getattr(n, "id", None), dict)
    }
    assert kinds == {"starter-chip"}, "a starter still fires the question"


def test_the_starters_still_show_the_question_they_will_ask():
    questions = texts(welcome_hero("Jash"), "starter-chip-question")
    assert all(q.endswith("?") or len(q) > 20 for q in questions)


def test_the_empty_state_sits_next_to_the_composer():
    style_css = Path("assets/style.css").read_text(encoding="utf-8")
    assert "justify-content: flex-end" in rule_for(
        style_css, ".chat-bot-text-area:has(.welcome-hero)"
    )


def test_the_placeholder_no_longer_types_at_the_reader():
    js = Path("assets/typewriter.js").read_text(encoding="utf-8")
    assert "setInterval" not in js and "setTimeout" not in js


# ── narrow screens ───────────────────────────────────────────────────────────


def test_the_rail_becomes_a_drawer_below_the_desktop_breakpoint():
    block = narrow_block(SHELL_CSS, 1024)
    assert "position: absolute" in block
    assert "translateX(-100%)" in block


def test_the_drawer_can_be_opened_and_closed_without_the_rail_on_screen():
    """Its own toggle goes off-screen with it, so there must be another way in."""
    from ui.shell.layout import app_shell

    shell = app_shell(1, "jash", "chat")
    toggles = {
        n.id["rail"] for n in walk(shell)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "va-rail-toggle"
    }
    assert {"navbar", "scrim"} <= toggles


def test_the_scrim_is_inert_while_the_rail_is_a_column():
    assert "pointer-events: none" in rule_for(SHELL_CSS, ".va-rail-scrim")
