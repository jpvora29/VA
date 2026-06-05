"""Semantic memory — durable per-user profile facts.

A small key/value store for facts that should persist and personalize the
experience (display name today; role/preferences later). Backed by the
``profile`` table in the app-state DB.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.store.db import app_engine, profile
from logger import get_logger

logger = get_logger(__name__)


def _coerce_uid(user_id: Any) -> Optional[int]:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def set_fact(user_id: Any, key: str, value: str) -> None:
    """Upsert a single profile fact for a user."""
    uid = _coerce_uid(user_id)
    if uid is None or not key:
        return
    stmt = sqlite_insert(profile).values(user_id=uid, key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[profile.c.user_id, profile.c.key],
        set_={"value": value},
    )
    try:
        with app_engine.begin() as conn:
            conn.execute(stmt)
    except Exception:  # pragma: no cover - profile writes are best-effort
        logger.exception("semantic.set_fact failed")


def get_profile(user_id: Any) -> dict[str, str]:
    """All profile facts for a user as a ``{key: value}`` dict."""
    uid = _coerce_uid(user_id)
    if uid is None:
        return {}
    with app_engine.connect() as conn:
        rows = conn.execute(
            select(profile.c.key, profile.c.value).where(profile.c.user_id == uid)
        ).all()
    return {r.key: r.value for r in rows}


def greeting_name(user_id: Any, fallback: str = "") -> str:
    """Best display name for greetings — ``display_name`` fact, else fallback."""
    facts = get_profile(user_id)
    name = (facts.get("display_name") or facts.get("username") or fallback or "").strip()
    return name
