"""In-process background-job registry for streaming chat turns.

Why threads (not Dash background callbacks / DiskCache): the LangGraph chat graph
uses an **in-memory** checkpointer, so HITL interrupt/resume only works within a
single process. A process-based background manager would run each turn in a
separate worker with its own checkpointer and break resume. Running the turn in a
daemon thread inside the same process keeps the checkpointer + singletons shared,
while still giving us real cooperative cancellation and live per-node streaming.

A `Job` is keyed by the chat `thread_id`. The worker thread streams the graph
node-by-node, recording the current node so the UI can show "Running X agent…",
and checks a `threading.Event` between nodes for cooperative cancellation
(LangGraph cannot kill a node mid-flight, so a stop takes effect at the next node
boundary). The Dash poll callback reads the job each tick and, on completion,
commits the final state to the chat transcript.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class Job:
    """A single in-flight (or finished) chat turn."""

    thread_id: str
    cancel: threading.Event = field(default_factory=threading.Event)
    current_node: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    done: bool = False
    cancelled: bool = False
    error: Optional[str] = None
    state: Dict[str, Any] = field(default_factory=dict)
    interrupt: Optional[dict] = None

    def elapsed_seconds(self) -> int:
        return int(time.time() - self.started_at)


_JOBS: Dict[str, Job] = {}
_LOCK = threading.Lock()


def start_job(thread_id: str, worker: Callable[[Job], None]) -> Job:
    """Register a fresh Job for `thread_id` and run `worker(job)` in a daemon thread.

    Any existing job for the same thread is cancelled and replaced.
    """
    with _LOCK:
        existing = _JOBS.get(thread_id)
        if existing is not None and not existing.done:
            existing.cancel.set()
        job = Job(thread_id=thread_id)
        _JOBS[thread_id] = job

    def _run() -> None:
        try:
            worker(job)
        except Exception as exc:  # noqa: BLE001 - surface to the UI, never crash the thread
            job.error = str(exc)
        finally:
            job.done = True

    threading.Thread(target=_run, name=f"chat-job-{thread_id}", daemon=True).start()
    return job


def get_job(thread_id: Optional[str]) -> Optional[Job]:
    if not thread_id:
        return None
    with _LOCK:
        return _JOBS.get(thread_id)


def cancel_job(thread_id: Optional[str]) -> None:
    job = get_job(thread_id)
    if job is not None:
        job.cancel.set()


def clear_job(thread_id: Optional[str]) -> None:
    if not thread_id:
        return
    with _LOCK:
        _JOBS.pop(thread_id, None)
