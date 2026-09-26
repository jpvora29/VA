"""Persisted turn traces — the observability ledger behind the token chip.

Each completed chat turn writes one row (:data:`core.store.db.turn_traces`).
`usage_summary` rolls them up per user so the operations view can answer "how
long do answers take, and what do they cost" without scraping log files.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, insert, select

from core.store.db import app_engine, turn_traces
from logger import get_logger

logger = get_logger(__name__)


def _uid(user_id: Any) -> Optional[int]:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def save_trace(user_id: Any, thread_id: str, trace: Dict[str, Any], *,
               question: str = "", route: str = "", shape: str = "") -> bool:
    """Append one turn's trace. Never raises — a meter must not fail a turn."""
    if not trace:
        return False
    tokens = trace.get("tokens") or {}
    try:
        with app_engine.begin() as conn:
            conn.execute(insert(turn_traces).values(
                user_id=_uid(user_id), thread_id=thread_id or "",
                question=(question or "")[:2000], route=route or "", shape=shape or "",
                status=str(trace.get("status") or "ok"),
                elapsed_ms=int(trace.get("elapsed_ms") or 0),
                llm_calls=int(trace.get("llm_calls") or 0),
                input_tokens=int(tokens.get("input_tokens") or 0),
                output_tokens=int(tokens.get("output_tokens") or 0),
                total_tokens=int(tokens.get("total_tokens") or 0),
                trace=json.dumps(trace, default=str),
            ))
        return True
    except Exception:  # pragma: no cover - observability is best effort
        logger.exception("Could not save the trace for thread %s", thread_id)
        return False


def recent_traces(user_id: Any, limit: int = 50) -> List[Dict[str, Any]]:
    """The user's latest turns, newest first, without the JSON body."""
    uid = _uid(user_id)
    if uid is None:
        return []
    with app_engine.connect() as conn:
        rows = conn.execute(
            select(turn_traces.c.thread_id, turn_traces.c.question, turn_traces.c.route,
                   turn_traces.c.status, turn_traces.c.elapsed_ms, turn_traces.c.llm_calls,
                   turn_traces.c.total_tokens, turn_traces.c.created_at)
            .where(turn_traces.c.user_id == uid)
            .order_by(desc(turn_traces.c.id)).limit(limit)
        ).all()
    return [dict(row._mapping) for row in rows]


def conversation_usage(thread_id: str) -> Dict[str, int]:
    """Token and time totals for one conversation, summed over its turns."""
    with app_engine.connect() as conn:
        row = conn.execute(
            select(func.count(), func.coalesce(func.sum(turn_traces.c.total_tokens), 0),
                   func.coalesce(func.sum(turn_traces.c.elapsed_ms), 0),
                   func.coalesce(func.sum(turn_traces.c.llm_calls), 0))
            .where(turn_traces.c.thread_id == thread_id)
        ).one()
    return {"turns": int(row[0]), "total_tokens": int(row[1]),
            "elapsed_ms": int(row[2]), "llm_calls": int(row[3])}


def usage_summary(user_id: Any, limit: int = 200) -> Dict[str, Any]:
    """p50/p95 latency and token totals over the user's recent turns."""
    traces = recent_traces(user_id, limit)
    if not traces:
        return {"turns": 0}
    times = sorted(t["elapsed_ms"] for t in traces)
    return {
        "turns": len(traces),
        "p50_ms": times[len(times) // 2],
        "p95_ms": times[min(len(times) - 1, int(len(times) * 0.95))],
        "total_tokens": sum(t["total_tokens"] for t in traces),
        "avg_tokens": sum(t["total_tokens"] for t in traces) // len(traces),
        "llm_calls": sum(t["llm_calls"] for t in traces),
    }
