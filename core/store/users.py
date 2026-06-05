"""User account helpers (lightweight, username-only — no passwords)."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import insert, select

from core.store.db import app_engine, users


def get_or_create_user(username: str) -> dict[str, Any]:
    """Return the user row for ``username``, creating it on first sign-in.

    Returns a plain dict ``{"id", "username"}``. Username is trimmed; empty
    usernames are rejected by the caller (the login callback), not here.
    """
    username = (username or "").strip()
    with app_engine.begin() as conn:
        row = conn.execute(
            select(users.c.id, users.c.username).where(users.c.username == username)
        ).first()
        if row is None:
            result = conn.execute(insert(users).values(username=username))
            user_id = int(result.inserted_primary_key[0])
        else:
            user_id = int(row.id)
    return {"id": user_id, "username": username}


def get_user(user_id: int | str) -> Optional[dict[str, Any]]:
    """Look up a user by id; ``None`` if not found."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    with app_engine.connect() as conn:
        row = conn.execute(
            select(users.c.id, users.c.username).where(users.c.id == uid)
        ).first()
    if row is None:
        return None
    return {"id": int(row.id), "username": row.username}
