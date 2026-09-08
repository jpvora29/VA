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
    # The ACCOUNT KEY, not a display name. Under SSO this is the person's email
    # address (or the provider's opaque subject id when the IdP sends no address);
    # in local mode it is whatever they typed. Unique either way, which is what
    # makes a returning user find their own conversations.
    Column("username", String, nullable=False, unique=True),
    # Who they are, as the identity provider describes them. Both are nullable
    # because every row written before SSO existed has neither, and a local sign-in
    # still has neither.
    Column("display_name", String, nullable=True),
    Column("subject", String, nullable=True, index=True),
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


# ── Decision Board ────────────────────────────────────────────────────────────
# Manually-authored business decisions, rendered as colour-coded sticky cards on
# a Kanban board. Deliberately separate from `episodes` (agent memory): a
# decision is an auditable application record and must never silently become
# factual agent memory. JSON-shaped columns (stakeholders, evidence, links) are
# stored as Text blobs, mirroring `conversations.data`.
decisions = Table(
    "decisions",
    metadata,
    Column("id", String, primary_key=True),  # uuid4 hex
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("title", String, nullable=False, default=""),
    Column("statement", Text, nullable=False, default=""),
    Column("rationale", Text, nullable=True),
    Column("discussion", Text, nullable=True),
    Column("owner", String, nullable=True),
    Column("stakeholders", Text, nullable=False, default="[]"),  # JSON list[str]
    # 'approved' | 'under_review' | 'blocked' | 'planned' | 'archived'
    Column("status", String, nullable=False, default="planned", index=True),
    Column("priority", String, nullable=False, default="med"),  # high|med|low
    Column("decision_date", String, nullable=True),  # ISO date string
    Column("due_date", String, nullable=True),  # ISO date string
    Column("pinned", Integer, nullable=False, default=0),  # 0/1 boolean
    Column("sort_order", Integer, nullable=False, default=0),  # order within column
    Column("evidence", Text, nullable=False, default="[]"),  # JSON list[dict]
    Column("links", Text, nullable=False, default="{}"),  # JSON {chats:[], ...}
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now(), onupdate=func.now()),
)


# Append-only audit trail for every decision mutation. "Reopen" is just a row
# with action='reopened'; nothing is ever updated or deleted here.
decision_revisions = Table(
    "decision_revisions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "decision_id",
        String,
        ForeignKey("decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    # 'created' | 'updated' | 'status_changed' | 'reopened'
    Column("action", String, nullable=False),
    Column("field", String, nullable=True),  # which field changed, when applicable
    Column("old_value", Text, nullable=True),
    Column("new_value", Text, nullable=True),
    Column("note", Text, nullable=True),  # free-text note (e.g. reopen reason)
    Column("created_at", DateTime, server_default=func.now(), index=True),
)


#: Columns added to `users` after the table shipped. ``create_all`` only creates
#: missing TABLES, so a database written before SSO existed keeps the old three
#: columns and every query naming a new one fails — on an app whose whole state
#: lives in one long-lived SQLite file, that is a crash on upgrade rather than a
#: theoretical one. SQLite's ADD COLUMN is cheap and idempotent here.
_USER_COLUMNS_ADDED = (("display_name", "TEXT"), ("subject", "TEXT"))


def _add_missing_user_columns() -> None:
    """Bring an existing ``users`` table up to the current schema."""
    from sqlalchemy import inspect, text

    inspector = inspect(app_engine)
    if "users" not in inspector.get_table_names():
        return
    present = {c["name"] for c in inspector.get_columns("users")}
    with app_engine.begin() as conn:
        for name, sql_type in _USER_COLUMNS_ADDED:
            if name not in present:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {sql_type}"))


def init_db() -> None:
    """Create all app-state tables if they don't yet exist (idempotent)."""
    metadata.create_all(app_engine)
    _add_missing_user_columns()


# Create tables eagerly on import so any first caller finds a ready schema.
init_db()
