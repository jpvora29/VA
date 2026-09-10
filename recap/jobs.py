"""In-process registry for recap runs, so the workspace can poll one.

A run reads whole decks and makes hundreds of model calls; Dash callbacks must return
in milliseconds. So the callback starts a :class:`RecapJob` in a daemon thread and an
interval callback reads its snapshot each tick — the same shape :mod:`mom.jobs` and
``ui.jobs`` use, for the same reason.

``snapshot`` is the only way to read a running job: it takes the lock once and hands
back a plain dict, so a poll can never see a half-written job.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from logger import get_logger
from recap.progress import label_for, percent_done, phase_for
from recap.run import RecapRequest, RecapResult, run_recap_pipeline

log = get_logger(__name__)


@dataclass
class RecapJob:
    """One run: what it is doing now, and what it produced."""

    job_id: str
    request: RecapRequest
    stage: Optional[str] = None
    message: str = "Starting"
    done: bool = False
    error: Optional[str] = None
    result: Optional[RecapResult] = None
    started_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def report(self, stage: str, message: str = "") -> None:
        """The pipeline's progress sink — called from the worker thread."""
        with self._lock:
            self.stage = stage
            self.message = message or label_for(stage)
        log.info("Recap[%s] %s: %s", self.job_id, stage, self.message)

    def succeed(self, result: RecapResult) -> None:
        with self._lock:
            self.result = result
            self.message = f"{result.pptx_path.name} is ready"
            self.done = True

    def fail(self, message: str) -> None:
        with self._lock:
            self.error = message
            self.done = True

    def snapshot(self) -> dict:
        """Everything the UI needs for one tick, read under the lock."""
        with self._lock:
            stage, message = self.stage, self.message
            done, error, result = self.done, self.error, self.result
        finished = done and error is None
        return {
            "job_id": self.job_id,
            "stage": stage,
            "phase": phase_for(stage),
            "step": label_for(stage),
            "message": message,
            "percent": percent_done(stage, finished=finished),
            "done": done,
            "error": error,
            "elapsed": int(time.time() - self.started_at),
            "filename": result.pptx_path.name if result else None,
            "client": result.client if result else None,
            "period": result.period if result else None,
            "takeaways": list(result.takeaway_titles[:5]) if result else [],
            "action_items": result.action_item_count if result else 0,
            "insights": result.insight_count if result else 0,
        }

    def pptx_path(self) -> Optional[str]:
        """The finished deck, or None while the run is still going."""
        with self._lock:
            return str(self.result.pptx_path) if self.result else None


_JOBS: Dict[str, RecapJob] = {}
_LOCK = threading.Lock()


def start_run(
    request: RecapRequest,
    runner: Callable[..., RecapResult] = run_recap_pipeline,
) -> RecapJob:
    """Register a job for ``request`` and run the pipeline in a daemon thread."""
    job = RecapJob(job_id=uuid.uuid4().hex[:12], request=request)
    with _LOCK:
        _JOBS[job.job_id] = job

    def work() -> None:
        try:
            job.succeed(runner(request, report=job.report))
        except Exception as exc:  # noqa: BLE001 - a failed run must reach the user
            log.exception("Recap[%s] failed", job.job_id)
            job.fail(str(exc) or exc.__class__.__name__)

    threading.Thread(target=work, name=f"recap-{job.job_id}", daemon=True).start()
    return job


def get_job(job_id: Optional[str]) -> Optional[RecapJob]:
    if not job_id:
        return None
    with _LOCK:
        return _JOBS.get(job_id)


def clear_job(job_id: Optional[str]) -> None:
    if not job_id:
        return
    with _LOCK:
        _JOBS.pop(job_id, None)
