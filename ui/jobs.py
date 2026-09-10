"""In-process background-job registry for streaming chat turns.

Threads keep graph execution separate from Dash rendering. The graph checkpointer
is durable, but this job registry is process-local. Multiple web workers require
a shared queue and job store; a database checkpoint alone does not provide that.

A `Job` is keyed by the chat `thread_id`. The worker thread streams the graph
node-by-node, recording the turn's progress (`ui.progress`) so the UI can show
what stage the answer is at, and checks a `threading.Event` between nodes for
cooperative cancellation
(LangGraph cannot kill a node mid-flight, so a stop takes effect at the next node
boundary). The worker saves the final transcript before publishing completion.
Dash polling only reads progress or the completed transcript.
"""
from __future__ import annotations

import threading
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ui.progress import Step


@dataclass
class Job:
    """A single in-flight (or finished) chat turn."""

    thread_id: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_id: int | str | None = None
    transcript: Dict[str, Any] = field(default_factory=dict)
    deleted: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    # How far along the turn is, in the user's language. Advanced by the worker
    # thread as named nodes are entered; read by the Dash poll callback.
    progress: Optional[Step] = None
    started_at: float = field(default_factory=time.time)
    done: bool = False
    cancelled: bool = False
    error: Optional[str] = None
    state: Dict[str, Any] = field(default_factory=dict)
    interrupt: Optional[dict] = None
    # Final-answer text streamed token-by-token by the graph's TokenStreamHandler.
    # The worker thread appends; the Dash poll thread reads — hence the lock.
    partial_text: str = ""
    _lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)

    def elapsed_seconds(self) -> int:
        return int(time.time() - self.started_at)

    def append_partial(self, text: str) -> None:
        """Thread-safe token sink for the streaming callback handler."""
        if not text:
            return
        with self._lock:
            self.partial_text += text

    def get_partial(self) -> str:
        with self._lock:
            return self.partial_text


_JOBS: Dict[str, Job] = {}
_LOCK = threading.Lock()


def start_job(thread_id: str, worker: Callable[[Job], None], *,
              prepare: Callable[[Job], None] | None = None,
              finalize: Callable[[Job], None] | None = None,
              user_id: int | str | None = None) -> Job:
    """Register a fresh Job for `thread_id` and run `worker(job)` in a daemon thread.

    A second launch shares the existing job; checkpoint writers never overlap.
    Finalization (including persistence) completes before `done` is published.
    """
    with _LOCK:
        existing = _JOBS.get(thread_id)
        if existing is not None and not existing.done:
            return existing
        job = Job(thread_id=thread_id, user_id=user_id)
        _JOBS[thread_id] = job

    threading.Thread(target=_run_job, args=(job, worker, prepare, finalize),
                     name=f"chat-job-{thread_id}", daemon=True).start()
    return job


def _run_job(job: Job, worker: Callable, prepare: Callable | None,
             finalize: Callable | None) -> None:
    try:
        if prepare is not None:
            with job._lock:
                if job.deleted:
                    return
                prepare(job)
        worker(job)
    except Exception as exc:  # surface to the UI, never crash the worker
        logging.getLogger(__name__).exception("Chat job %s failed (thread %s)", job.id, job.thread_id)
        job.error = str(exc)
    finally:
        if finalize is not None:
            try:
                with job._lock:
                    if not job.deleted:
                        finalize(job)
            except Exception as exc:
                logging.getLogger(__name__).exception("Finalizing chat job %s failed", job.id)
                job.error = f"Could not save the answer: {exc}"
        job.done = True


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


def discard_job(thread_id: str, delete: Callable[[], None]) -> None:
    """Serialize deletion with final persistence so a worker cannot resurrect it."""
    job = get_job(thread_id)
    if job is None:
        delete()
        return
    with job._lock:
        job.deleted = True
        job.cancel.set()
        delete()
