"""In-process registry for deck builds, so Setup can poll one instead of waiting on it.

A build reads the warehouse a few thousand times and has a model write around a hundred
commentary columns. Even at its fastest that is minutes; on a wide carrier it was hours.
Dash callbacks must return in milliseconds, and a callback that does not is not merely
slow — it *loses its answer*:

  * the browser gives up on a request left open that long, so the stores are never
    written and Setup sits there looking as though Generate did nothing;
  * the stores keep the values they already had, which are the PREVIOUS deck — so
    opening Canvas by hand showed the deck before this one.

Both of those are the same bug, and this is the fix the rest of the app already uses:
the callback starts a :class:`DeckJob` in a daemon thread and an interval callback reads
its snapshot each tick (:mod:`mom.jobs`, :mod:`ui.jobs`).

``snapshot`` is the only way to read a running job: it takes the lock once and hands back
a plain dict, so a poll can never see a half-written job.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from logger import get_logger
from studio.authoring.generate import DeckDocuments, build_documents
from studio.authoring.progress import label_for, percent_done
from studio.commentary_mode import CommentaryUnavailable

log = get_logger(__name__)

Builder = Callable[..., DeckDocuments]


@dataclass
class DeckJob:
    """One build: what it is doing now, and the documents it produced."""

    job_id: str
    selection: Dict[str, Any]
    phase: Optional[str] = None
    message: str = "Starting"
    done: bool = False
    error: Optional[str] = None
    #: True when re-running the identical selection could succeed — a rate limit, a
    #: timed-out endpoint, a section the model could not write this time. False for a
    #: configuration mistake, where "try again" sends the author round a loop that
    #: cannot close.
    retryable: bool = False
    result: Optional[DeckDocuments] = None
    started_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def report(self, phase: str, message: str) -> None:
        """The build's progress sink — called from the worker thread."""
        with self._lock:
            self.phase, self.message = phase, message
        log.info("studio deck[%s] %s: %s", self.job_id, phase, message)

    def succeed(self, result: DeckDocuments) -> None:
        with self._lock:
            self.result = result
            self.message = "Your deck is ready."
            self.done = True

    def fail(self, message: str, *, retryable: bool = False) -> None:
        with self._lock:
            self.error = message
            self.retryable = retryable
            self.done = True

    def snapshot(self) -> dict:
        """Everything the UI needs for one tick, read under the lock."""
        with self._lock:
            phase, message, done, error = self.phase, self.message, self.done, self.error
            retryable = self.retryable
            slides = int((self.result.tdoc or {}).get("n_slides", 0)) if self.result else 0
        return {
            "job_id": self.job_id,
            "phase": phase,
            "step": label_for(phase),
            "message": message,
            "percent": percent_done(phase, finished=done and error is None),
            "done": done,
            "error": error,
            "retryable": retryable,
            # The SCOPE this build was started with, so the progress view can say which
            # deck is being made. The selection is frozen at start, so it is safe to read
            # outside the lock — and the author who picked "Country-wise" twenty minutes
            # ago should not have to remember that they did.
            "scope": str(self.selection.get("template_scope") or "all"),
            "elapsed": int(time.time() - self.started_at),
            "slides": slides,
        }

    def documents(self) -> Optional[DeckDocuments]:
        """The finished documents, or None while the build is still going."""
        with self._lock:
            return self.result


_JOBS: Dict[str, DeckJob] = {}
_LOCK = threading.Lock()


def start_build(selection: Dict[str, Any], builder: Builder = build_documents) -> DeckJob:
    """Register a job for ``selection`` and build it in a daemon thread."""
    job = DeckJob(job_id=uuid.uuid4().hex[:12], selection=dict(selection or {}))
    with _LOCK:
        _JOBS[job.job_id] = job

    def work() -> None:
        try:
            job.succeed(builder(job.selection, report=job.report))
        except CommentaryUnavailable as exc:
            # ``COMMENTARY_MODE=ai_required`` refused to ship deterministic prose. That is
            # the mode working, not a crash, so it is logged as a refusal and carries
            # whether re-running could plausibly help.
            log.warning("studio deck[%s] refused: %s", job.job_id, exc)
            job.fail(str(exc), retryable=exc.retryable)
        except Exception as exc:  # noqa: BLE001 — a failed build must reach the user
            log.exception("studio deck[%s] failed", job.job_id)
            job.fail(str(exc) or exc.__class__.__name__)

    threading.Thread(target=work, name=f"studio-deck-{job.job_id}", daemon=True).start()
    return job


def get_job(job_id: Optional[str]) -> Optional[DeckJob]:
    if not job_id:
        return None
    with _LOCK:
        return _JOBS.get(job_id)


def clear_job(job_id: Optional[str]) -> None:
    if not job_id:
        return
    with _LOCK:
        _JOBS.pop(job_id, None)
