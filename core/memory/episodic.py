"""Long-term episodic memory store.

Persists a user's questions, explicit feedback, and (most valuably) SQL
error→fix pairs across sessions, so the agent can recall "last time a similar
query failed, this corrected SQL worked". Backed by the ``episodes`` table in the
app-state DB (``core/store/db.py``).

``recall`` is deliberately simple — recency + case-insensitive substring overlap,
no vector store — which is enough to surface relevant prior fixes as few-shots.
"""
from __future__ import annotations

import json
from typing import Any, Optional, Protocol

from sqlalchemy import insert, select

from core.store.db import app_engine, episodes
from logger import get_logger

logger = get_logger(__name__)


class EpisodicStore(Protocol):
    """Read/write interface the agent nodes depend on (DIP)."""

    def recall(self, user_id: str, query: str, k: int = 5) -> list[dict[str, Any]]: ...
    def remember(self, user_id: str, episode: dict[str, Any]) -> None: ...


def _coerce_uid(user_id: Any) -> Optional[int]:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(t) > 2}


class SqliteEpisodicStore:
    """SQLite-backed :class:`EpisodicStore` with typed convenience writers."""

    # ── generic protocol ────────────────────────────────────────────────
    def remember(self, user_id: Any, episode: dict[str, Any]) -> None:
        uid = _coerce_uid(user_id)
        if uid is None:
            return
        try:
            with app_engine.begin() as conn:
                conn.execute(
                    insert(episodes).values(
                        user_id=uid,
                        kind=episode.get("kind", "question"),
                        conversation_id=episode.get("conversation_id"),
                        content=episode.get("content"),
                        route=episode.get("route"),
                        rating=episode.get("rating"),
                        meta=json.dumps(episode.get("meta")) if episode.get("meta") else None,
                    )
                )
        except Exception:  # pragma: no cover - memory must never break a turn
            logger.exception("episodic.remember failed")

    def recall(self, user_id: Any, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Most relevant recent episodes for a user (recency + token overlap)."""
        uid = _coerce_uid(user_id)
        if uid is None:
            return []
        with app_engine.connect() as conn:
            rows = conn.execute(
                select(
                    episodes.c.kind,
                    episodes.c.content,
                    episodes.c.route,
                    episodes.c.rating,
                    episodes.c.meta,
                    episodes.c.created_at,
                )
                .where(episodes.c.user_id == uid)
                .order_by(episodes.c.created_at.desc())
                .limit(200)
            ).all()

        q_tokens = _tokens(query or "")
        scored: list[tuple[int, dict[str, Any]]] = []
        for r in rows:
            overlap = len(q_tokens & _tokens(r.content or "")) if q_tokens else 0
            scored.append((overlap, _row_to_dict(r)))
        # Stable sort: relevance first, recency (already ordered) preserved on ties.
        scored.sort(key=lambda s: s[0], reverse=True)
        return [d for _, d in scored[:k]]

    # ── typed writers ───────────────────────────────────────────────────
    def record_question(
        self, user_id: Any, conversation_id: str, question: str, route: str | None
    ) -> None:
        self.remember(
            user_id,
            {
                "kind": "question",
                "conversation_id": conversation_id,
                "content": question,
                "route": route,
            },
        )

    def record_feedback(
        self,
        user_id: Any,
        conversation_id: str,
        rating: str,
        note: str | None = None,
    ) -> None:
        self.remember(
            user_id,
            {
                "kind": "feedback",
                "conversation_id": conversation_id,
                "content": note,
                "rating": rating,
            },
        )

    def record_sql_fix(
        self,
        user_id: Any,
        route: str,
        question: str,
        failed_sql: str,
        error: str,
        working_sql: str,
    ) -> None:
        """Persist a verified error→fix pair (the working SQL actually executed)."""
        self.remember(
            user_id,
            {
                "kind": "sql_fix",
                "content": question,
                "route": route,
                "meta": {
                    "failed_sql": failed_sql,
                    "error": str(error)[:2000],
                    "working_sql": working_sql,
                },
            },
        )

    # ── typed readers ───────────────────────────────────────────────────
    def recent_questions(self, user_id: Any, limit: int = 20) -> list[str]:
        return [e["content"] for e in self._recent(user_id, "question", limit) if e.get("content")]

    def recent_feedback(self, user_id: Any, limit: int = 20) -> list[dict[str, Any]]:
        return self._recent(user_id, "feedback", limit)

    def recall_sql_fixes(
        self, user_id: Any, route: str, question: str, k: int = 3
    ) -> list[dict[str, str]]:
        """Return up to ``k`` similar past fixes as ``{question, sql}`` few-shots."""
        uid = _coerce_uid(user_id)
        if uid is None:
            return []
        with app_engine.connect() as conn:
            rows = conn.execute(
                select(episodes.c.content, episodes.c.meta)
                .where(
                    (episodes.c.user_id == uid)
                    & (episodes.c.kind == "sql_fix")
                    & (episodes.c.route == route)
                )
                .order_by(episodes.c.created_at.desc())
                .limit(100)
            ).all()

        q_tokens = _tokens(question or "")
        scored: list[tuple[int, dict[str, str]]] = []
        for r in rows:
            try:
                meta = json.loads(r.meta) if r.meta else {}
            except (TypeError, ValueError):
                meta = {}
            working = meta.get("working_sql")
            if not working:
                continue
            overlap = len(q_tokens & _tokens(r.content or "")) if q_tokens else 0
            scored.append((overlap, {"question": r.content or "", "sql": working}))
        scored.sort(key=lambda s: s[0], reverse=True)
        # Only surface examples with at least some token overlap to avoid noise.
        return [d for score, d in scored[:k] if score > 0]

    def _recent(self, user_id: Any, kind: str, limit: int) -> list[dict[str, Any]]:
        uid = _coerce_uid(user_id)
        if uid is None:
            return []
        with app_engine.connect() as conn:
            rows = conn.execute(
                select(
                    episodes.c.kind,
                    episodes.c.content,
                    episodes.c.route,
                    episodes.c.rating,
                    episodes.c.meta,
                    episodes.c.created_at,
                )
                .where((episodes.c.user_id == uid) & (episodes.c.kind == kind))
                .order_by(episodes.c.created_at.desc())
                .limit(limit)
            ).all()
        return [_row_to_dict(r) for r in rows]


def _row_to_dict(r: Any) -> dict[str, Any]:
    try:
        meta = json.loads(r.meta) if r.meta else None
    except (TypeError, ValueError):
        meta = None
    return {
        "kind": r.kind,
        "content": r.content,
        "route": r.route,
        "rating": r.rating,
        "meta": meta,
        "created_at": str(r.created_at),
    }


# Module-level singleton used by the UI + graph nodes.
episodic_store = SqliteEpisodicStore()
