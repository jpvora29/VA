"""Read-only engines over the analytics warehouse file.

The warehouse is shared (a OneDrive folder users can write to), so the app must never
modify it: one user's app adding an index to their synced copy is enough for OneDrive
to fork the file into conflict copies. ``PRAGMA query_only`` makes every write on the
connection fail instead, whatever the folder permissions say. Indexes are built once,
by whoever publishes the file — ``python -m studio.index_warehouse <path>``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def readonly_sqlite_engine(path: Any) -> Engine:
    """A SQLAlchemy engine over ``path`` on which every write raises."""
    engine = create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _make_query_only)
    return engine


def _make_query_only(dbapi_connection: Any, _connection_record: Any) -> None:
    dbapi_connection.execute("PRAGMA query_only = ON")
