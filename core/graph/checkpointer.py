"""Per-workflow LangGraph checkpointers.

Chat and pitch intentionally use separate checkpointer instances so their
state histories can evolve independently. The default adapter is in-memory;
the builder functions make it straightforward to swap chat or pitch to a
Sqlite/Postgres saver later without touching workflow code.
"""
from __future__ import annotations

from typing import Any, Optional


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


def build_chat_checkpointer() -> Any:
    """Singleton checkpointer for the interactive chat workflow."""
    global _chat_checkpointer
    if _chat_checkpointer is None:
        _chat_checkpointer = _new_memory_checkpointer()
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
