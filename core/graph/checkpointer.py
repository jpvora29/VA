"""Per-workflow LangGraph checkpointers.

Chat and pitch intentionally use separate checkpointer instances so their
state histories can evolve independently.

The chat checkpointer is **persistent** (SQLite, via ``langgraph-checkpoint-sqlite``)
so a reopened conversation resumes its full graph memory — message history,
routing context — even across server restarts. Because a conversation's id is its
LangGraph ``thread_id``, clicking a saved chat lines up with its stored checkpoint
and the next turn continues the thread instead of starting cold. It writes its own
``checkpoints*`` tables into the same ``app_state.db`` file used by the readable app
state (``core/store/db.py``). Pitch keeps an in-memory saver.

If the Sqlite saver package is unavailable we fall back to an in-memory saver, so
the app still runs (losing only cross-restart continuity).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

logger = logging.getLogger(__name__)


_chat_checkpointer: Optional[Any] = None
_pitch_checkpointer: Optional[Any] = None


def _new_memory_checkpointer() -> Any:
    """Return the available LangGraph in-memory saver for this installed version."""
    try:
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    except ImportError:  # older LangGraph releases
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


def _new_sqlite_checkpointer() -> Any:
    """Persistent SQLite saver over the app-state DB, or None if unavailable."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        from core.store.db import app_db_path

        # check_same_thread=False: the streaming chat job runs in a daemon thread.
        conn = sqlite3.connect(app_db_path(), check_same_thread=False)
        saver = SqliteSaver(conn)
        saver.setup()  # idempotent: creates checkpoints tables on first run
        return saver
    except Exception:  # pragma: no cover - degrade gracefully to in-memory
        logger.warning(
            "Persistent SqliteSaver unavailable; chat memory will not survive "
            "restarts.",
            exc_info=True,
        )
        return None


def build_chat_checkpointer() -> Any:
    """Singleton persistent checkpointer for the interactive chat workflow."""
    global _chat_checkpointer
    if _chat_checkpointer is None:
        _chat_checkpointer = _new_sqlite_checkpointer() or _new_memory_checkpointer()
    return _chat_checkpointer


def build_pitch_checkpointer() -> Any:
    """Singleton checkpointer for pitch/docx workflows and pitch question runs."""
    global _pitch_checkpointer
    if _pitch_checkpointer is None:
        _pitch_checkpointer = _new_memory_checkpointer()
    return _pitch_checkpointer


def checkpoint_config(thread_id: str) -> dict[str, dict[str, str]]:
    """Build the LangGraph config required by checkpointer-backed invocations."""
    return {"configurable": {"thread_id": thread_id}}


def build_checkpointer() -> Any:
    """Back-compat alias for callers that still expect a default checkpointer."""
    return build_chat_checkpointer()
