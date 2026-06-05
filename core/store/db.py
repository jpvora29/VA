"""SQLite app-state database: schema + engine.

A dedicated SQLite file (``APP_DB_PATH``, default ``<project>/app_state.db``) that
backs user accounts, saved conversations, episodic memory, and semantic profile
facts. This is intentionally NOT the analytics warehouse engine in
``config.db_config`` — app bookkeeping must never mutate warehouse data.

The LangGraph chat checkpointer (see ``core/graph/checkpointer.py``) points its
``SqliteSaver`` at the *same* file but uses its own ``checkpoints`` tables, so a
single ``app_state.db`` carries both the readable app state and the agent's
per-thread graph memory.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)


def app_db_path() -> str:
    """Filesystem path to the app-state SQLite file."""
    env = os.environ.get("APP_DB_PATH")
    if env:
        return env
    # core/store/db.py -> project root is three levels up.
    return str(Path(__file__).resolve().parents[2] / "app_state.db")


app_engine = create_engine(
    f"sqlite:///{app_db_path()}",
    # The chat job runs in a daemon thread; allow cross-thread access.
    connect_args={"check_same_thread": False},
)

metadata = MetaData()


users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String, nullable=False, unique=True),
    Column("created_at", DateTime, server_default=func.now()),
)


conversations = Table(
    "conversations",
    metadata,
    # id == LangGraph thread_id, so a reopened chat lines up with its checkpoint.
    Column("id", String, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("title", String, nullable=False, default=""),
    Column("data", Text, nullable=False, default="{}"),  # JSON chat-store blob
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now(), onupdate=func.now()),
)


episodes = Table(
    "episodes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    # 'question' | 'feedback' | 'sql_fix'
    Column("kind", String, nullable=False, index=True),
    Column("conversation_id", String, nullable=True),
    Column("content", Text, nullable=True),
    Column("route", String, nullable=True),
    Column("rating", String, nullable=True),  # 'up' | 'down' for feedback
    Column("meta", Text, nullable=True),  # JSON: extra fields (failed_sql, etc.)
    Column("created_at", DateTime, server_default=func.now(), index=True),
)


profile = Table(
    "profile",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("key", String, nullable=False),
    Column("value", Text, nullable=True),
    UniqueConstraint("user_id", "key", name="uq_profile_user_key"),
)


def init_db() -> None:
    """Create all app-state tables if they don't yet exist (idempotent)."""
    metadata.create_all(app_engine)


# Create tables eagerly on import so any first caller finds a ready schema.
init_db()
