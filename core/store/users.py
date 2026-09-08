"""User accounts — one row per person, however they signed in.

There are two sign-ins and ONE account table, which is the point. ``username`` is the
account KEY: under SSO it is the address the identity provider vouched for, in local
mode it is what the person typed. Everything downstream (conversations, episodes,
semantic profile) keys off the row id, so neither path needs to know which one made the
row, and a deployment can turn SSO on without orphaning anyone's history.

No passwords are stored here under either path. Local mode has none by design; under SSO
the credential never reaches this app at all — only the claims the IdP signed.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import insert, select, update

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


def get_or_create_sso_user(identity) -> dict[str, Any]:
    """The user row for a signed-in :class:`~core.auth.identity.Identity`.

    Matched on ``username`` (the account key), so a person who used the local sign-in
    with their email address before SSO was switched on keeps their conversations rather
    than starting again beside a duplicate row.

    The IdP's display name and subject are refreshed on every sign-in: a name changes,
    and the row may predate SSO and carry neither.
    """
    key = (identity.key or "").strip()
    if not key:
        raise ValueError("an identity with no key cannot be signed in")
    with app_engine.begin() as conn:
        row = conn.execute(select(users.c.id).where(users.c.username == key)).first()
        if row is None:
            result = conn.execute(insert(users).values(
                username=key, display_name=identity.display_name or None,
                subject=identity.subject or None,
            ))
            user_id = int(result.inserted_primary_key[0])
        else:
            user_id = int(row.id)
            conn.execute(update(users).where(users.c.id == user_id).values(
                display_name=identity.display_name or None,
                subject=identity.subject or None,
            ))
    return {"id": user_id, "username": identity.label}


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
