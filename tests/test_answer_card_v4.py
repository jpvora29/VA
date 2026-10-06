"""Answer card v4: clear sections, the position table behind every chart, and the
chat-switching / pin-menu fixes that shipped with it.

Run:  pytest tests/test_answer_card_v4.py -q -o pythonpath=.
"""
from pathlib import Path

import plotly.graph_objects as go

from core.analytics import positioning as P
from ui.answer_layout import DOWN, RISK, UP, WARN, Section, badge_for, takeaways_and_next_steps
from ui.components.evidence import evidence_panel
from ui.evidence import EvidenceView, lift_title


def walk(node):
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from walk(child)
    elif children is not None and not isinstance(children, str):
        yield from walk(children)


def classes(node):
    return [getattr(n, "className", "") or "" for n in walk(node)]


def ids(node):
    return [getattr(n, "id", None) for n in walk(node) if getattr(n, "id", None) is not None]


# ── The position table ──────────────────────────────────────────────────────

def test_rank_change_is_a_column_and_reads_as_places_gained():
    moved = P.SlicePosition(slice="Marine", carrier_premium=40.0, rank=1, prior_rank=3)
    row = P._row(moved, "Product_Line")
    assert list(row)[-2:] == [P.RANK_CHANGE, P.RANK_FIELD]
    assert row[P.RANK_CHANGE] == 2  # rank 3 -> rank 1 is two places GAINED
    assert P.PositioningPack((moved,), "Product_Line", subject="X").column_kinds()[
        P.RANK_CHANGE] == P.SIGNED_COUNT


def test_rank_change_is_blank_when_no_prior_year_was_compared():
    row = P._row(P.SlicePosition(slice="Marine", rank=1), "Product_Line")
    assert row[P.RANK_CHANGE] is None  # not compared is not "did not move"


# ── The evidence panel ──────────────────────────────────────────────────────

def _chart(label="Premium"):
    return EvidenceView(label, ["Line", "Premium"], [{"Line": "A", "Premium": 1.0}],
                        figure=go.Figure(), title=f"{label} by line")


def _position(label="Position"):
    kinds = {"Product line": P.TEXT, P.MARSH_PREMIUM: P.MONEY, P.CARRIER_PREMIUM: P.MONEY}
    return EvidenceView(label, list(kinds), [{"Product line": "A", P.MARSH_PREMIUM: 2.0,
                                              P.CARRIER_PREMIUM: 1.0}], column_kinds=kinds)


def test_the_position_table_is_the_table_side_of_every_chart():
    panel = evidence_panel([_position(), _chart("Premium"), _chart("Quarterly")], idx=7,
                           pane_ids=[70, 71, 72], label="Supporting evidence")
    assert "is-paired" in panel.className
    # The tabs are the charts only; the table is not a tab of its own.
    tabs = [i for i in ids(panel) if isinstance(i, dict) and i.get("type") == "ev-tab"]
    assert len(tabs) == 2
    # ONE Chart/Table switch, in the panel header, driving the whole panel.
    toggles = [i for i in ids(panel) if isinstance(i, dict) and i.get("type") == "chart-toggle-data"]
    assert toggles == [{"type": "chart-toggle-data", "idx": 70}]
    table_side = next(n for n in walk(panel)
                      if getattr(n, "id", None) == {"type": "chart-table", "idx": 70})
    assert any("ev-table-block" in c for c in classes(table_side))
    assert "ev-panel-label" in classes(panel)


def test_several_markets_stack_their_tables_under_their_names():
    panel = evidence_panel([_position("Singapore"), _position("Hong Kong"), _chart()], idx=1,
                           pane_ids=[10, 11, 12])
    titles = [n.children for n in walk(panel) if getattr(n, "className", "") == "ev-view-title"]
    assert "Singapore" in titles and "Hong Kong" in titles


def test_without_a_position_table_each_chart_keeps_its_own_rows():
    panel = evidence_panel([_chart("Premium"), _chart("Quarterly")], idx=2, pane_ids=[20, 21])
    assert "is-paired" not in panel.className
    toggles = [i for i in ids(panel) if isinstance(i, dict) and i.get("type") == "chart-toggle-data"]
    assert len(toggles) == 2


def test_a_chart_title_moves_from_the_plot_to_the_panel_header():
    figure = go.Figure(layout={"title": {"text": "Premium by line"}, "margin": {"t": 78}})
    assert lift_title(figure) == "Premium by line"
    assert not figure.layout.title.text
    assert figure.layout.margin.t == 38  # the legend keeps its rows


# ── Takeaways ───────────────────────────────────────────────────────────────

def test_a_takeaway_chip_quotes_the_first_movement_in_its_own_words():
    assert badge_for(Section("x", "- Property grew 60% and took share")).text == "Property ▲ 60%"
    assert badge_for(Section("x", "- Premium fell 33.3% to $4.0M")).tone == DOWN
    assert badge_for(Section("x", "- Marine rose from 2nd to 1st among carriers")).text == "Rank #2 → #1"
    assert badge_for(Section("x", "- Cyber +25.0% on the year")).tone == UP


def test_no_figure_means_no_chip_and_a_watch_out_says_so():
    assert badge_for(Section("x", "- The book is concentrated in one line")) is None
    assert badge_for(Section("Watch-outs", "- Thin data", RISK)).tone == WARN


def test_what_it_means_becomes_the_next_step_not_a_takeaway():
    sections = [Section("What moved", "- a"), Section("What it means", "- b", "action")]
    findings, steps = takeaways_and_next_steps(sections)
    assert [s.title for s in findings] == ["What moved"]
    assert [s.title for s in steps] == ["What it means"]


# ── Switching conversations and the pin menu ────────────────────────────────

def test_the_old_chat_is_hidden_outright_while_switching():
    css = Path("assets/va_shell_chat_v2.css").read_text(encoding="utf-8")
    rule = css.split(".chat-viewport.is-switching > #chat-box {", 1)[1].split("}", 1)[0]
    # Opacity alone lost to the fade-in animation's fill from the last switch.
    assert "visibility: hidden" in rule and "animation: none" in rule


def test_only_one_loading_label_is_visible():
    css = Path("assets/chat_reliability.css").read_text(encoding="utf-8")
    rule = css.split(".chat-loading {", 1)[1].split("}", 1)[0]
    assert "clip:" in rule  # announced to screen readers, not drawn


def test_the_row_menu_opens_on_click_not_focus():
    css = Path("assets/va_shell.css").read_text(encoding="utf-8")
    assert ".conv-item-actions.is-open .conv-menu { display: block; }" in css
    assert ".conv-item-actions:focus-within .conv-menu" not in css
    assert "is-open" in Path("assets/chat_sidebar.js").read_text(encoding="utf-8")


def test_decision_board_does_not_wear_the_pinned_chat_icon():
    source = Path("ui/components/sidebar.py").read_text(encoding="utf-8")
    board = source.split('html.Span("Decision Board")', 1)[0].rsplit("html.I(", 1)[1]
    assert "pin" not in board


# ── Money: millions, billions from $1B, never K or raw ──────────────────────

def test_money_reads_in_millions_and_billions_only():
    from core.analytics.money_units import money_text

    assert money_text(8_237_000) == "$8.2M"
    assert money_text(412_345) == "$0.4M"
    assert money_text(40_000) == "$0.04M"
    assert money_text(1_310_000_000) == "$1.3B"
    assert money_text(-3_400_000, signed=True) == "-$3.4M"


def test_every_surface_uses_the_same_rule():
    from core.answers.facts import format_value as commentary
    from core.boardroom.money import format_money
    from ui.chart_functions import format_value as chart

    assert commentary(412_345, "currency") == chart(412_345, "money") == format_money(412_345) == "$0.4M"


def test_a_money_axis_states_one_unit():
    from ui.chart_functions import money_ticks

    _, labels = money_ticks([2.4e9, 0.8e9])
    assert all(label.endswith("B") for label in labels)
    _, labels = money_ticks([160e6, 40e6])
    assert all(label.endswith("M") for label in labels)


# ── Sending from the welcome screen, and deleting the open chat ─────────────

def test_the_welcome_screen_is_hidden_through_the_viewport():
    js = Path("assets/chat_experience.js").read_text(encoding="utf-8")
    css = Path("assets/va_shell_chat_v2.css").read_text(encoding="utf-8")
    # The hero is a Dash component whose class a re-render resets; the viewport is not.
    assert 'viewport.classList.add("va-sending")' in js
    assert ".chat-viewport.va-sending #chat-box .welcome-hero" in css


def test_the_working_card_waits_for_the_answer_not_the_run():
    js = Path("assets/chat_experience.js").read_text(encoding="utf-8")
    assert "if (!now && was) { finishPending(); }" in js
    assert 'turnCount(".turn-assistant") > pending.answers) { clearPending(); }' in js


def test_deleting_the_open_chat_lands_on_a_new_chat():
    js = Path("assets/chat_experience.js").read_text(encoding="utf-8")
    block = js.split('var del = target.closest(\'[id*="conv-del"]\');', 1)[1].split("return;", 1)[0]
    assert ".conv-item-active" in block and "newChat.click()" in block


# ── Coloured arrows reach the page ──────────────────────────────────────────

def test_answer_prose_is_one_html_block_so_delta_spans_survive():
    from ui.components.answer_markdown import to_html_block

    block = to_html_block("- **Property** — $5.2M ▲ 18.0%, x < y\n- Marine -3.1pp")
    # Dash's Markdown drops INLINE html tag by tag; a block is injected whole.
    assert block.startswith('<div class="md-block">\n') and block.endswith("\n</div>")
    assert "\n\n" not in block
    assert '<span class="delta delta-up">▲ 18.0%</span>' in block
    assert '<span class="delta delta-down">▼ 3.1pp</span>' in block
    assert "&lt; y" in block and "<y" not in block
