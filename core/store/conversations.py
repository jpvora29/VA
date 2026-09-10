"""Saved-conversation persistence.

A conversation is the full ``chat-store`` dict (messages, followups, thread_id…)
serialized as a single JSON blob, keyed by ``id == thread_id``. The sidebar lists
conversations per user; reopening one rehydrates ``chat-store`` and — because the
id is the LangGraph thread_id — the agent's graph memory lines up too.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.store.db import app_engine, conversations
from logger import get_logger

logger = get_logger(__name__)

_TITLE_MAX = 60


def _derive_title(chat_history: dict[str, Any]) -> str:
    """Keep saved titles; derive new ones from the first question without an LLM."""
    cached = (chat_history.get("title") or "").strip()
    if cached:
        return cached if len(cached) <= _TITLE_MAX else cached[: _TITLE_MAX - 1] + "…"
    for msg in chat_history.get("messages", []) or []:
        if msg.get("type") == "HumanMessage" and (msg.get("content") or "").strip():
            text = msg["content"].strip().replace("\n", " ")
            return text if len(text) <= _TITLE_MAX else text[: _TITLE_MAX - 1] + "…"
    return "New chat"


def list_conversations(user_id: int | str) -> list[dict[str, Any]]:
    """Conversations for a user, newest-updated first: ``[{id, title, updated_at}]``."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return []
    with app_engine.connect() as conn:
        rows = conn.execute(
            select(
                conversations.c.id,
                conversations.c.title,
                conversations.c.updated_at,
            )
            .where(conversations.c.user_id == uid)
            .order_by(conversations.c.updated_at.desc())
        ).all()
    return [
        {"id": r.id, "title": r.title or "New chat", "updated_at": str(r.updated_at)}
        for r in rows
    ]


def save_conversation(
    user_id: int | str, conv_id: str, chat_history: dict[str, Any]
) -> bool:
    """Upsert the full transcript for ``conv_id`` under ``user_id``.

    No-ops when there is nothing worth saving (no id, no messages) so empty
    "New chat" shells don't clutter the sidebar.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if not conv_id or not (chat_history or {}).get("messages"):
        return False

    title = _derive_title(chat_history)
    data = json.dumps(chat_history, default=str)
    stmt = sqlite_insert(conversations).values(
        id=conv_id, user_id=uid, title=title, data=data
    )
    # On conflict, refresh title/data/updated_at (SQLite ON CONFLICT upsert).
    stmt = stmt.on_conflict_do_update(
        index_elements=[conversations.c.id],
        set_={"title": title, "data": data, "updated_at": func.now()},
        where=conversations.c.user_id == uid,
    )
    try:
        with app_engine.begin() as conn:
            result = conn.execute(stmt)
        return result.rowcount == 1
    except Exception:  # pragma: no cover - persistence must never break a turn
        logger.exception("Failed to save conversation %s", conv_id)
        return False


def save_chat_edit(user_id: int | str, conv_id: str, chat: dict, *, recovering: bool = False) -> bool:
    """Update an existing turn only. A stale browser cannot overwrite a newer job.

    The data equality predicate also guards changes between reading and writing;
    deletion is never treated as an instruction to recreate a conversation.
    """
    from sqlalchemy import update
    with app_engine.begin() as conn:
        where = (conversations.c.id == conv_id) & (conversations.c.user_id == int(user_id))
        previous = conn.execute(select(conversations.c.data).where(where)).scalar_one_or_none()
        if previous is None:
            return False
        stored = json.loads(previous)
        if stored.get("_job_id") != chat.get("_job_id") or (stored.get("_running") and not recovering):
            return False
        result = conn.execute(update(conversations).where(where & (conversations.c.data == previous)).values(
            data=json.dumps(chat, default=str), title=_derive_title(chat), updated_at=func.now()))
        return result.rowcount == 1


def load_conversation(user_id: int | str, conv_id: str) -> Optional[dict[str, Any]]:
    """Return the stored ``chat-store`` dict for a conversation, or ``None``."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    with app_engine.connect() as conn:
        row = conn.execute(
            select(conversations.c.data).where(
                (conversations.c.id == conv_id) & (conversations.c.user_id == uid)
            )
        ).first()
    if row is None:
        return None
    try:
        return json.loads(row.data)
    except (TypeError, ValueError):
        logger.warning("Corrupt conversation blob for %s", conv_id)
        return None


def delete_conversation(user_id: int | str, conv_id: str) -> None:
    """Remove a conversation owned by ``user_id``."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return
    with app_engine.begin() as conn:
        conn.execute(
            delete(conversations).where(
                (conversations.c.id == conv_id) & (conversations.c.user_id == uid)
            )
        )
