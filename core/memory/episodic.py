"""Long-term episodic memory store — Phase 3 stub.

Persists facts and prior-error patterns keyed by user_id across sessions,
so the agent can recall "last time you asked this it failed because X".
See `project-decision-dual-memory`.
"""
from __future__ import annotations

from typing import Any, Protocol


class EpisodicStore(Protocol):  # pragma: no cover - Phase 3
    """Read/write interface the agent nodes will depend on (DIP)."""

    def recall(self, user_id: str, query: str, k: int = 5) -> list[dict[str, Any]]: ...
    def remember(self, user_id: str, episode: dict[str, Any]) -> None: ...
