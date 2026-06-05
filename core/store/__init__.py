"""Application-state persistence (separate from the analytics warehouse DB).

Holds user accounts, saved conversations, episodic memory, and semantic profile
facts in a dedicated SQLite file (``app_state.db`` by default, overridable via the
``APP_DB_PATH`` env var). Kept entirely separate from ``config.db_config`` so the
analytics warehouse is never touched by app bookkeeping.
"""
from core.store.db import app_engine, init_db, metadata

__all__ = ["app_engine", "init_db", "metadata"]
