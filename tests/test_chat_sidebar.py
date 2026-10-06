"""The Chatbot rail: grouped history, pinning, search, and the empty-state composer gap."""
from datetime import datetime, timedelta, timezone
import pathlib

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import StaticPool

from ui.components.chat_history import (
    clock_time,
    group_conversations,
    local_moment,
    relative_age,
    row_meta,
)

NOW = datetime(2026, 10, 6, 14, 14, 30)


def stored(local: datetime) -> str:
    """A local moment as the store writes it: UTC, no offset."""
    return local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def chat(cid, age, pinned=False, title=None):
    return {"id": cid, "title": title or cid, "updated_at": stored(NOW - age), "pinned": pinned}


# ── pure grouping ─────────────────────────────────────────────────────────────


def test_stored_utc_is_read_as_local_time():
    assert local_moment(stored(NOW)) == NOW.replace(microsecond=0)
    assert local_moment("") is None
    assert local_moment("not a date") is None


def test_groups_read_pinned_then_today_yesterday_week_then_months():
    groups = group_conversations(
        [
            chat("now", timedelta(0)),
            chat("pin", timedelta(days=3), pinned=True),
            chat("yday", timedelta(days=1)),
            chat("week", timedelta(days=4)),
            chat("sept", timedelta(days=20)),
        ],
        NOW,
    )
    assert [g.label for g in groups] == [
        "Pinned", "Today", "Yesterday", "Previous 7 days", "September 2026"]
    assert [g.date_label for g in groups[:3]] == ["", "Oct 6, 2026", "Oct 5, 2026"]
    assert [r.id for g in groups for r in g.rows] == ["pin", "now", "yday", "week", "sept"]


def test_a_pinned_chat_is_listed_once():
    groups = group_conversations([chat("a", timedelta(0), pinned=True)], NOW)
    assert [g.key for g in groups] == ["pinned"]


def test_row_meta_is_clock_time_then_age():
    assert row_meta(NOW - timedelta(seconds=20), NOW) == ("2:14 PM", "Just now")
    assert row_meta(NOW - timedelta(hours=21), NOW) == ("5:14 PM", "21h ago")
    assert row_meta(NOW - timedelta(days=5), NOW) == ("Thu 1 Oct", "5d ago")
    assert row_meta(NOW - timedelta(days=60), NOW) == ("Fri 7 Aug",)
    assert row_meta(None, NOW) == ()


def test_clock_and_age_edges():
    assert clock_time(datetime(2026, 1, 1, 0, 5)) == "12:05 AM"
    assert clock_time(datetime(2026, 1, 1, 12, 0)) == "12:00 PM"
    assert relative_age(NOW + timedelta(minutes=1), NOW) == "Just now"  # clock skew
    assert relative_age(NOW - timedelta(minutes=5), NOW) == "5m ago"
    assert relative_age(NOW - timedelta(days=14), NOW) == "2w ago"


# ── store ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def repository(monkeypatch):
    from core.store import conversations as repo
    from core.store.db import metadata

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    metadata.create_all(engine)
    monkeypatch.setattr(repo, "app_engine", engine)
    yield repo
    engine.dispose()


def _save(repo, user, cid):
    repo.save_conversation(user, cid, {"thread_id": cid, "messages": [
        {"type": "HumanMessage", "content": cid}]})


def test_pinning_flips_without_moving_the_chat_in_time(repository):
    _save(repository, 7, "a")
    with repository.app_engine.begin() as conn:
        conn.execute(text("UPDATE conversations SET updated_at = '2026-09-01 10:00:00'"))

    assert repository.list_conversations(7)[0]["pinned"] is False
    assert repository.toggle_conversation_pin(7, "a")
    row = repository.list_conversations(7)[0]
    assert row["pinned"] is True
    assert row["updated_at"] == "2026-09-01 10:00:00"
    assert repository.toggle_conversation_pin(7, "a")
    assert repository.list_conversations(7)[0]["pinned"] is False


def test_nobody_pins_another_users_chat(repository):
    _save(repository, 7, "a")
    assert not repository.toggle_conversation_pin(8, "a")
    assert repository.list_conversations(7)[0]["pinned"] is False


def test_an_existing_database_gains_the_pinned_column(monkeypatch):
    from core.store import db

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)"))
        conn.execute(text("CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id INTEGER, "
                          "title TEXT, data TEXT, created_at DATETIME, updated_at DATETIME)"))
        conn.execute(text("INSERT INTO conversations (id, user_id, title, data) "
                          "VALUES ('old', 1, 't', '{}')"))
    monkeypatch.setattr(db, "app_engine", engine)

    db._add_missing_columns()
    db._add_missing_columns()  # idempotent

    with engine.connect() as conn:
        assert conn.execute(select(db.conversations.c.pinned)).scalar_one() == 0


# ── rendering ─────────────────────────────────────────────────────────────────


def _find(component, predicate, found=None):
    found = [] if found is None else found
    if predicate(component):
        found.append(component)
    children = getattr(component, "children", None)
    for child in children if isinstance(children, list) else [children]:
        if child is not None and not isinstance(child, str):
            _find(child, predicate, found)
    return found


def _classes(component):
    return (getattr(component, "className", "") or "").split()


def test_sidebar_rows_carry_open_pin_and_delete_controls():
    from dash import html
    from ui.components.sidebar import conversation_list_children

    tree = html.Div(conversation_list_children(
        [chat("a", timedelta(0)), chat("b", timedelta(days=2), pinned=True)], "a", now=NOW))
    rows = _find(tree, lambda c: "conv-item" in _classes(c))
    assert [r.children[0].id["id"] for r in rows] == ["b", "a"]  # pinned first
    active = [r for r in rows if "conv-item-active" in _classes(r)]
    assert [r.children[0].id["id"] for r in active] == ["a"]
    ids = {(c.id["type"], c.id["id"]) for c in _find(tree, lambda c: isinstance(
        getattr(c, "id", None), dict))}
    assert {("conv-item", "a"), ("conv-pin", "a"), ("conv-del", "a"), ("conv-pin", "b")} <= ids
    labels = [c.children for c in _find(tree, lambda c: "conv-menu-item" in _classes(c))]
    assert any("Unpin" in str(label) for label in labels)


def test_empty_history_says_so():
    from ui.components.sidebar import conversation_list_children

    assert "No chats yet" in str(conversation_list_children([], None))


def test_rail_has_search_and_help_footer():
    from ui.components.sidebar import app_sidebar

    rail = app_sidebar([], "jash")
    assert _find(rail, lambda c: getattr(c, "id", None) == "conv-search")
    assert _find(rail, lambda c: "sidebar-help" in _classes(c))
    assert _find(rail, lambda c: getattr(c, "id", None) == "conversation-list")


# ── keys and layout ───────────────────────────────────────────────────────────


def test_ctrl_k_searches_chats_and_shift_esc_focuses_the_composer():
    sidebar_js = pathlib.Path("assets/chat_sidebar.js").read_text(encoding="utf-8")
    chat_js = pathlib.Path("assets/chat_experience.js").read_text(encoding="utf-8")
    assert 'event.key !== "k"' in sidebar_js
    assert 'event.key === "k"' not in chat_js
    assert 'event.key === "Escape" && event.shiftKey' in chat_js

    from ui.components.chatbot import composer_hints
    assert "search chats" in str(composer_hints())


def test_empty_state_composer_keeps_clear_of_the_starters():
    css = pathlib.Path("assets/va_shell_chat_v2.css").read_text(encoding="utf-8")
    rule = css.split(".chatbot-area .chat-column:has(#chat-box .welcome-hero) .input-area {")[1]
    rule = rule.split("}")[0]
    assert "padding-top: clamp(32px" in rule
