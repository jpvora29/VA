"""The evidence panel: one answer's evidence, shown in one place.

Covers the pin rule, the card's chip, and the end-to-end path a fallback turn
takes: evidence rows -> rule-chosen chart (no model) -> stored views -> the
card (chip + evidence) and the panel (the same evidence, its own ids, the
"why this chart" line).

Run:  pytest tests/test_evidence_side_panel.py -q
"""

from __future__ import annotations

from dash.development.base_component import Component

from core.agents.analyst.chart_picker import ChartFocus, pick_charts
from ui.analysis import answer_count, dock_target, live_pin
from ui.components.analysis_dock import (
    DOCK_NS,
    dock_body,
    evidence_chip,
    workspace_class,
)
from ui.components.chatbot import ai_message
from ui.evidence import build_views

RANKING = [
    {"Carrier": "ZURICH", "Premium": 9.0},
    {"Carrier": "GENERALI", "Premium": 7.0},
    {"Carrier": "AXA", "Premium": 5.0},
    {"Carrier": "ALLIANZ", "Premium": 8.0},
]


def walk(node):
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, Component):
        yield from walk(children)
    elif isinstance(children, (list, tuple)):
        for child in children:
            if isinstance(child, Component):
                yield from walk(child)


def classes(node) -> set[str]:
    return {
        part
        for n in walk(node)
        for part in str(getattr(n, "className", "") or "").split()
    }


def _history(*answers_with_evidence: bool) -> dict:
    messages: list[dict] = []
    for i, has_evidence in enumerate(answers_with_evidence):
        messages.append({"type": "HumanMessage", "content": f"Q{i}"})
        messages.append(
            {"type": "AIMessage", "content": "Premium grew.", "question": f"Q{i}"}
        )
        if has_evidence:
            messages.append({"type": "Evidence", "views": [{"rows": RANKING}]})
    return {"messages": messages}


# ── which answer the panel shows ───────────────────────────────────────────


def test_a_pin_holds_until_the_next_answer_arrives():
    history = _history(True, True)
    focus = {"idx": 1, "answers": answer_count(history)}
    assert live_pin(focus, history) == 1
    assert dock_target(history, live_pin(focus, history)).idx == 1

    history["messages"] += _history(True)["messages"]
    assert live_pin(focus, history) is None
    assert dock_target(history, None).idx == len(history["messages"]) - 2


def test_no_pin_follows_the_newest_answer_with_evidence():
    history = _history(True, False)
    assert dock_target(history, live_pin(None, history)).idx == 1


def test_collapsing_the_panel_is_one_class_on_the_workspace():
    assert workspace_class(dock_open=True) == "chat-workspace"
    assert workspace_class(dock_open=False) == "chat-workspace dock-hidden"


# ── the card's chip ────────────────────────────────────────────────────────


def test_the_chip_says_what_the_evidence_is():
    views = build_views(
        [
            {
                "rows": RANKING,
                "chart_data": {"chart_type": "bar", "x": "Carrier", "y": ["Premium"]},
            },
            {"rows": RANKING},
        ]
    )
    chip = evidence_chip(3, views, has_drivers=True)
    assert chip.id == {"type": "evidence-focus", "idx": 3}
    assert "1 chart · 1 table · drivers" in str(chip)


def test_an_answer_without_evidence_has_no_chip():
    card = ai_message("Premium grew 12%.", True, idx=1)
    assert "answer-evidence-chip" not in classes(card)


def test_an_answer_being_edited_has_no_chip():
    views = build_views([{"rows": RANKING}])
    card = ai_message(
        "Premium grew 12%.", True, idx=1, evidence=views, pane_ids=[0], editing=True
    )
    assert "answer-evidence-chip" not in classes(card)


# ── end to end: rows -> rule chart -> card and panel ───────────────────────


def test_a_fallback_turn_is_charted_by_the_rules_and_shown_in_both_homes():
    evidence = [{"flow": "gpr", "lens": "peer", "rows": RANKING, "scope": {}}]
    charts = pick_charts(
        "how does generali rank on premium",
        evidence,
        ChartFocus(subject=(("Carrier", "GENERALI"),)),
    )
    assert len(charts) == 1
    chart_data = charts[0]["chart_data"]
    assert (chart_data["rule"], chart_data["chart_type"]) == ("ranking", "bar")
    assert chart_data["highlight"] == "GENERALI"

    # Stored the way the analyst stores it, then rendered as the transcript does.
    history = {
        "messages": [
            {"type": "HumanMessage", "content": "rank"},
            {
                "type": "AIMessage",
                "content": "Generali ranks third.",
                "question": "rank",
            },
            {"type": "Evidence", "views": charts},
        ]
    }
    views = build_views(charts)
    assert views[0].has_chart and "highlighted" in views[0].reason

    card = ai_message(
        "Generali ranks third.", True, idx=1, evidence=views, pane_ids=[0]
    )
    card_classes = classes(card)
    assert {
        "answer-evidence-chip",
        "answer-evidence",
        "ev-chart-reason",
    } <= card_classes

    panel = dock_body(dock_target(history, None))
    assert "ev-chart-reason" in classes(panel)
    panel_ids = [
        n.id
        for n in walk(panel)
        if isinstance(getattr(n, "id", None), dict) and "idx" in n.id
    ]
    assert panel_ids and all(str(i["idx"]).startswith(DOCK_NS) for i in panel_ids)


def test_the_picker_draws_no_chart_for_rows_no_rule_fits():
    evidence = [{"flow": "gpr", "lens": "peer", "rows": RANKING[:2], "scope": {}}]
    assert pick_charts("premium", evidence) == []
