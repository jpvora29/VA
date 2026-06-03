"""Deterministic pre-execution SQL validation for the chat flows.

Two guards, run before the real query executes:

1. `assert_read_only(sql)` — single-statement + SELECT/WITH allow-list (deny writes/DDL).
   Stronger and clearer than the old `(?i)join` regex.
2. `dry_run_explain(session, sql)` — `EXPLAIN <sql>` inside a rolled-back transaction so
   missing tables/columns and syntax errors surface BEFORE the real query runs.

Both return ``None`` when the SQL is acceptable, or a human-readable error string that the
execute node feeds to the existing SQL-fixer loop.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy.sql import text

# Statement keywords that must never appear at the start of a chat-generated query.
_DENY = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE",
    "TRUNCATE", "PRAGMA", "ATTACH", "DETACH", "VACUUM", "REINDEX", "GRANT",
    "REVOKE", "BEGIN", "COMMIT", "ROLLBACK",
}
_ALLOW_START = {"SELECT", "WITH"}


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)          # line comments
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)  # block comments
    return sql


def _statements(sql: str) -> list[str]:
    """Split on top-level semicolons (not inside single-quoted string literals)."""
    parts: list[str] = []
    buf: list[str] = []
    in_str = False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
        if ch == ";" and not in_str:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def assert_read_only(sql: str) -> Optional[str]:
    """Return an error string if ``sql`` is not a single read-only SELECT/WITH query."""
    if not sql or not sql.strip():
        return "Empty SQL query."

    cleaned = _strip_comments(sql)
    statements = _statements(cleaned)
    if len(statements) > 1:
        return "Multiple SQL statements are not allowed; expected a single SELECT query."

    stmt = statements[0]
    first = re.match(r"\s*([A-Za-z]+)", stmt)
    if not first or first.group(1).upper() not in _ALLOW_START:
        return "Only read-only SELECT/WITH queries are allowed."

    # Defence in depth: reject any write/DDL keyword as a standalone token anywhere.
    tokens = {t.upper() for t in re.findall(r"[A-Za-z]+", stmt)}
    denied = tokens & _DENY
    if denied:
        return f"Disallowed SQL keyword(s) for a read-only query: {sorted(denied)}."

    return None


def dry_run_explain(session: Any, sql: str) -> Optional[str]:
    """``EXPLAIN`` the query in a rolled-back transaction; return the error if it fails.

    SQLite compiles the statement during EXPLAIN, so missing tables/columns and syntax
    errors are raised here without touching data.
    """
    stmt = sql.strip().rstrip(";")
    try:
        session.execute(text(f"EXPLAIN {stmt}"))
        return None
    except Exception as exc:  # noqa: BLE001 - surface the message to the fixer
        return f"Pre-execution EXPLAIN failed: {exc}"
    finally:
        # EXPLAIN does not mutate, but roll back to keep the session pristine.
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
