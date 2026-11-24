"""The chat sidebar grouped by client, with previews and status dots.

Covers the summary read from a stored chat, the client grouping, the rendered
rail, and the store path end to end: a chat saved with a scoped answer comes
back from ``list_conversations`` filed under its client, and an old chat saved
before the columns existed is backfilled without moving in time.

Run:  pytest tests/test_chat_sidebar_clients.py -q
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from dash import html
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from core.store.chat_summary import (
    ANSWERED,
    NEEDS_INPUT,
    WORKING,
    client_of,
    first_sentence,
    summarize_chat,
)
from ui.components.chat_history import (
    ChatRow,
    client_slug,
    group_conversations,
    row_line,
    status_tone,
)
from ui.components.sidebar import conversation_list_children

NOW = datetime(2026, 11, 12, 15, 0, 0)

ZURICH_SG = [
    {"key": "carrier", "value": "ZURICH"},
    {"key": "country", "value": "Singapore"},
]


def stored(local: datetime) -> str:
    return local.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def chat(cid, age=timedelta(0), *, client="", preview="", status="", pinned=False):
    return {
        "id": cid,
        "title": cid,
        "updated_at": stored(NOW - age),
        "pinned": pinned,
        "client": client,
        "preview": preview,
        "status": status,
    }


def answered_chat(
    content="Premium grew 30% to $390M. Property led it.", scope=ZURICH_SG
):
    return {
        "messages": [
            {"type": "HumanMessage", "content": "How is Zurich doing?"},
            {"type": "AIMessage", "content": content, "scope": scope},
        ]
    }


# ── the summary ────────────────────────────────────────────────────────────


def test_the_client_is_the_carrier_and_market_of_the_answer():
    assert client_of(ZURICH_SG) == "Zurich · Singapore"
    assert client_of([{"key": "carrier", "value": "AIG"}]) == "AIG"
    assert client_of([{"key": "country", "value": "Singapore"}]) == ""


def test_the_preview_is_the_answers_first_sentence_without_markdown():
    assert first_sentence("## Summary\n**Premium grew 30%** to $390M. Then more.") == (
        "Premium grew 30% to $390M."
    )
    assert first_sentence("- [Property](#) led the book.") == "Property led the book."
    long = first_sentence("x" * 200)
    assert len(long) == 90 and long.endswith("…")


def test_a_follow_up_naming_no_carrier_keeps_the_chats_client():
    history = answered_chat()
    history["messages"] += [
        {"type": "HumanMessage", "content": "And Marine?"},
        {"type": "AIMessage", "content": "Marine fell 4%.", "scope": []},
    ]
    summary = summarize_chat(history)
    assert summary.client == "Zurich · Singapore"
    assert summary.preview == "Marine fell 4%."


@pytest.mark.parametrize(
    ("history", "status"),
    [
        ({**answered_chat(), "_running": True}, WORKING),
        (
            {
                "messages": [
                    *answered_chat()["messages"],
                    {"type": "ClarifyCard", "payload": {}},
                ]
            },
            NEEDS_INPUT,
        ),
        (answered_chat(), ANSWERED),
        ({"messages": [{"type": "HumanMessage", "content": "hi"}]}, ""),
    ],
)
def test_the_status_says_what_the_chat_is_waiting_on(history, status):
    assert summarize_chat(history).status == status


# ── grouping ───────────────────────────────────────────────────────────────


def test_groups_read_pinned_then_clients_then_recency():
    groups = group_conversations(
        [
            chat("a", client="Zurich · Singapore"),
            chat("b", timedelta(hours=1), client="AIG · Hong Kong"),
            chat("c", timedelta(hours=2)),
            chat("d", timedelta(hours=3), client="Zurich · Singapore"),
            chat("e", timedelta(hours=4), client="AIG · Hong Kong", pinned=True),
        ],
        NOW,
    )
    assert [(g.kind, g.label) for g in groups] == [
        ("pinned", "Pinned"),
        ("client", "Zurich · Singapore"),
        ("client", "AIG · Hong Kong"),
        ("recent", "Today"),
    ]
    assert [r.id for r in groups[1].rows] == ["a", "d"]
    assert [r.id for r in groups[2].rows] == ["b"]  # the pinned chat is listed once


def test_client_keys_are_stable_slugs():
    assert client_slug("Zurich · Singapore") == "zurich-singapore"


def test_status_tones_and_lines():
    row = ChatRow("a", "a", False, NOW, status="working")
    assert (status_tone(row, NOW), row_line(row)) == ("working", "Working…")
    row = ChatRow("a", "a", False, NOW, status="needs_input")
    assert (status_tone(row, NOW), row_line(row)) == ("needs-you", "Needs your answer")
    row = ChatRow(
        "a", "a", False, NOW - timedelta(hours=2), preview="Grew 30%", status="answered"
    )
    assert (status_tone(row, NOW), row_line(row)) == ("fresh", "Grew 30%")
    row = ChatRow("a", "a", False, NOW - timedelta(days=3), status="answered")
    assert (status_tone(row, NOW), row_line(row)) == ("older", "")


# ── rendering ──────────────────────────────────────────────────────────────


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    for child in children if isinstance(children, list) else [children]:
        if child is not None and not isinstance(child, str):
            yield from _walk(child)


def _render(active_id=None):
    conversations = [
        chat("a", client="Zurich · Singapore", preview="Grew 30% to $390M"),
        chat("b", timedelta(hours=1), client="AIG · Hong Kong", status="working"),
        chat("c", timedelta(hours=2)),
    ]
    return conversation_list_children(conversations, active_id, NOW)


def test_the_rail_labels_clients_and_folds_each_one():
    blocks = _render()
    names = [getattr(b, "className", "") for b in blocks]
    assert names[0] == "conv-section-label" and blocks[0].children == "Clients"
    details = [b for b in blocks if isinstance(b, html.Details)]
    assert len(details) == 2
    assert [d.open for d in details] == [True, False]  # the newest client is open


def test_the_open_chats_client_is_the_one_shown_open():
    details = [b for b in _render(active_id="b") if isinstance(b, html.Details)]
    assert [d.open for d in details] == [False, True]


def test_rows_show_the_preview_or_what_they_wait_on_and_are_searchable_by_client():
    rows = {
        n.id["id"]: n
        for block in _render()
        for n in _walk(block)
        if isinstance(getattr(n, "id", None), dict) and n.id.get("type") == "conv-item"
    }
    assert "Grew 30% to $390M" in str(rows["a"])
    assert "Working…" in str(rows["b"])
    items = [
        n
        for block in _render()
        for n in _walk(block)
        if "conv-item" in str(getattr(n, "className", "")).split()
    ]
    assert any(
        "zurich · singapore" in n.to_plotly_json()["props"]["data-title"] for n in items
    )


# ── end to end: save -> list -> grouped rail ───────────────────────────────


@pytest.fixture
def repository(monkeypatch):
    from core.store import conversations as repo
    from core.store.db import metadata

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    metadata.create_all(engine)
    monkeypatch.setattr(repo, "app_engine", engine)
    yield repo
    engine.dispose()


def test_a_saved_answer_is_filed_under_its_client(repository):
    assert repository.save_conversation(7, "t1", answered_chat())
    [row] = repository.list_conversations(7)
    assert (row["client"], row["preview"], row["status"]) == (
        "Zurich · Singapore",
        "Premium grew 30% to $390M.",
        ANSWERED,
    )
    blocks = conversation_list_children([row], "t1")
    assert any(isinstance(b, html.Details) for b in blocks)


def test_an_old_chat_is_backfilled_once_without_moving_in_time(repository):
    import json

    with repository.app_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO conversations (id, user_id, title, data, updated_at) "
                "VALUES ('old', 7, 'old', :data, '2026-09-01 10:00:00')"
            ),
            {"data": json.dumps(answered_chat())},
        )
    [row] = repository.list_conversations(7)
    assert row["client"] == "Zurich · Singapore"
    assert row["updated_at"] == "2026-09-01 10:00:00"
    assert repository.backfill_summaries(7) == 0  # nothing left to fill
