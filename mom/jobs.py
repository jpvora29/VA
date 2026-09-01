"""In-process registry for MoM runs, so the workspace can poll one.

A run takes minutes and makes dozens of model calls; Dash callbacks must return in
milliseconds. So the callback starts a :class:`MoMJob` in a daemon thread and an
interval callback reads its snapshot each tick — the same shape ``ui.jobs`` uses for a
streaming chat turn, for the same reason.

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
from mom.pipeline import MoMRequest, MoMResult, run_mom_pipeline
from mom.progress import label_for, percent_done

log = get_logger(__name__)


@dataclass
class MoMJob:
    """One run: what it is doing now, and what it produced."""

    job_id: str
    request: MoMRequest
    phase: Optional[str] = None
    message: str = "Starting"
    done: bool = False
    error: Optional[str] = None
    result: Optional[MoMResult] = None
    started_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def report(self, phase: str, message: str) -> None:
        """The pipeline's progress sink — called from the worker thread."""
        with self._lock:
            self.phase, self.message = phase, message
        log.info("MoM[%s] %s: %s", self.job_id, phase, message)

    def succeed(self, result: MoMResult) -> None:
        with self._lock:
            self.result = result
            self.message = f"{result.docx_path.name} is ready"
            self.done = True

    def fail(self, message: str) -> None:
        with self._lock:
            self.error = message
            self.done = True

    def snapshot(self) -> dict:
        """Everything the UI needs for one tick, read under the lock."""
        with self._lock:
            phase, message = self.phase, self.message
            done, error, result = self.done, self.error, self.result
        return {
            "job_id": self.job_id,
            "phase": phase,
            "step": label_for(phase),
            "message": message,
            "percent": percent_done(phase, finished=done and error is None),
            "done": done,
            "error": error,
            "elapsed": int(time.time() - self.started_at),
            "filename": result.docx_path.name if result else None,
            "client": result.client if result else None,
            "topics": [
                f"{pair['umbrella_tag']} / {pair['sub_tag']}"
                for pair in (result.priority_pairs if result else [])[:5]
            ],
            "llm_calls": result.llm_calls if result else 0,
        }

    def docx_path(self) -> Optional[str]:
        """The finished document, or None while the run is still going."""
        with self._lock:
            return str(self.result.docx_path) if self.result else None


_JOBS: Dict[str, MoMJob] = {}
_LOCK = threading.Lock()


def start_run(request: MoMRequest, runner: Callable[..., MoMResult] = run_mom_pipeline) -> MoMJob:
    """Register a job for ``request`` and run the pipeline in a daemon thread."""
    job = MoMJob(job_id=uuid.uuid4().hex[:12], request=request)
    with _LOCK:
        _JOBS[job.job_id] = job

    def work() -> None:
        try:
            job.succeed(runner(request, report=job.report))
        except Exception as exc:  # noqa: BLE001 - a failed run must reach the user
            log.exception("MoM[%s] failed", job.job_id)
            job.fail(str(exc) or exc.__class__.__name__)

    threading.Thread(target=work, name=f"mom-{job.job_id}", daemon=True).start()
    return job


def get_job(job_id: Optional[str]) -> Optional[MoMJob]:
    if not job_id:
        return None
    with _LOCK:
        return _JOBS.get(job_id)


def clear_job(job_id: Optional[str]) -> None:
    if not job_id:
        return
    with _LOCK:
        _JOBS.pop(job_id, None)
