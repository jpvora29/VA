"""What a build actually spent its time on — per model call, and per phase.

A QBR build is minutes of waiting, and until now the only evidence of where those minutes
went was a stopwatch and a guess. "Two hours" was diagnosed as an orchestration problem
because the call arithmetic said so, not because anything measured it — and a change that
cuts 54 calls to 9 is worth nothing if the endpoint was throttling the whole time.

So every model call reports itself here: which phase asked for it, which tier and deployment
answered, how long it waited, whether it succeeded, and if not, *what kind* of failure it
was. A rate limit and a bad deployment name are both "the call failed" in a log line and
completely different problems.

    with telemetry.job("Zurich / all"):
        with telemetry.phase("authorship"):
            ...                          # the model calls record themselves
    # -> one summary line per job, and job.summary() for a test to assert on

**Threads, deliberately.** The commentary writers run in a ``ThreadPoolExecutor``
(:mod:`studio.parallel`), and pool threads do not inherit a ``ContextVar`` — which is fine
for :mod:`studio.memo`, where a miss only costs a recomputation, and useless here, where a
miss would silently drop the very calls that make a build slow. So the active job is a
module global behind a lock. One build at a time per process is the truth of the app
anyway: :mod:`studio.authoring.jobs` refuses a second one while the first is in flight.

Pure reporting. Nothing here changes what a build does, and a build with no job open
records nothing and costs a dict lookup.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)


# ── what one model call cost ─────────────────────────────────────────────────

#: The phases a model call can belong to. Free-form strings would do; naming them means a
#: summary can report them in a fixed order and a typo shows up as an empty row.
AUTHOR = "author"
VERIFY = "verify"
REPAIR = "repair"
ENHANCE = "enhance"          # the optional story/layout/critic agents
OTHER = "other"

_PHASE_ORDER = (AUTHOR, VERIFY, REPAIR, ENHANCE, OTHER)


@dataclass(frozen=True)
class ModelCall:
    """One request to a model endpoint, and what came back."""

    node: str
    phase: str = OTHER
    tier: str = ""
    deployment: str = ""
    seconds: float = 0.0
    status: str = "ok"                     # ok | empty | error
    attempt: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    failure: str = ""                      # see classify_failure
    fields: Tuple[str, ...] = ()           # the commentary field ids in this batch

    @property
    def ok(self) -> bool:
        return self.status == "ok"


# ── classifying a failure, because retry policy depends on which kind it is ──

# Substring → category. Matched against the exception's text, lowercased. Ordered most
# specific first: a 429 body often also contains the word "error".
_FAILURE_SIGNS: Tuple[Tuple[str, str], ...] = (
    ("429", "rate_limit"),
    ("rate limit", "rate_limit"),
    ("too many requests", "rate_limit"),
    ("timeout", "timeout"),
    ("timed out", "timeout"),
    ("connection", "connection"),
    ("401", "auth"),
    ("403", "auth"),
    ("unauthorized", "auth"),
    ("api key", "auth"),
    ("deploymentnotfound", "config"),
    ("404", "config"),
    ("invalid_request", "config"),
    ("400", "config"),
    ("500", "server"),
    ("502", "server"),
    ("503", "server"),
    ("504", "server"),
    ("validation", "parse"),
    ("json", "parse"),
)

#: The categories worth trying again. Everything else is a configuration mistake that a
#: second identical request cannot fix — see :func:`is_transient`.
_TRANSIENT = frozenset({"rate_limit", "timeout", "connection", "server"})


def classify_failure(exc: BaseException) -> str:
    """Which KIND of failure this is: rate_limit, timeout, auth, config, parse, server…

    Text matching, because the exception types differ by SDK version and by whether the
    error arrived through LangChain, openai, or httpx — and the wording of an Azure error
    body has been stabler than any of them.
    """
    text = f"{type(exc).__name__} {exc}".lower()
    return next((name for sign, name in _FAILURE_SIGNS if sign in text), "unknown")


def is_transient(failure: str) -> bool:
    """True when retrying the identical request could plausibly succeed.

    An auth or config failure is not transient: retrying it burns the retry budget and
    delays the actionable error the operator needs to see.
    """
    return failure in _TRANSIENT


# ── one job's record ─────────────────────────────────────────────────────────


@dataclass
class JobTelemetry:
    """Everything one build recorded. Mutated from worker threads under ``_LOCK``."""

    label: str = "build"
    started: float = field(default_factory=time.perf_counter)
    calls: List[ModelCall] = field(default_factory=list)
    phase_seconds: Dict[str, float] = field(default_factory=dict)
    counters: Dict[str, int] = field(default_factory=dict)

    @property
    def seconds(self) -> float:
        return time.perf_counter() - self.started

    def summary(self) -> "JobSummary":
        return summarize(self)


@dataclass(frozen=True)
class JobSummary:
    """The numbers a run is judged on — what a benchmark asserts and a log line prints."""

    label: str
    seconds: float
    calls: int
    calls_by_phase: Dict[str, int]
    failures_by_kind: Dict[str, int]
    p50: float
    p95: float
    slowest: float
    input_tokens: int
    output_tokens: int
    phase_seconds: Dict[str, float]
    counters: Dict[str, int]

    def as_line(self) -> str:
        """One line, because a summary nobody reads is not instrumentation."""
        phases = " ".join(f"{k}={v}" for k, v in self.calls_by_phase.items() if v)
        fails = " ".join(f"{k}={v}" for k, v in sorted(self.failures_by_kind.items()))
        counts = " ".join(f"{k}={v}" for k, v in sorted(self.counters.items()))
        timings = " ".join(f"{k}={v:.1f}s" for k, v in self.phase_seconds.items())
        return (f"job={self.label} total={self.seconds:.1f}s calls={self.calls} [{phases}] "
                f"p50={self.p50:.1f}s p95={self.p95:.1f}s max={self.slowest:.1f}s "
                f"tokens={self.input_tokens}in/{self.output_tokens}out"
                + (f" phases[{timings}]" if timings else "")
                + (f" failures[{fails}]" if fails else "")
                + (f" counters[{counts}]" if counts else ""))


def _percentile(values: Sequence[float], pct: float) -> float:
    """The ``pct`` percentile by nearest rank — no numpy for six numbers."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(pct / 100 * len(ordered)))))
    return ordered[rank - 1]


def summarize(job: JobTelemetry) -> JobSummary:
    """A finished (or running) job as the numbers worth reporting. Pure."""
    latencies = [c.seconds for c in job.calls]
    by_phase = {phase: sum(1 for c in job.calls if c.phase == phase) for phase in _PHASE_ORDER}
    failures: Dict[str, int] = {}
    for call in job.calls:
        if call.failure:
            failures[call.failure] = failures.get(call.failure, 0) + 1
    return JobSummary(
        label=job.label,
        seconds=job.seconds,
        calls=len(job.calls),
        calls_by_phase=by_phase,
        failures_by_kind=failures,
        p50=_percentile(latencies, 50),
        p95=_percentile(latencies, 95),
        slowest=max(latencies, default=0.0),
        input_tokens=sum(c.input_tokens for c in job.calls),
        output_tokens=sum(c.output_tokens for c in job.calls),
        phase_seconds=dict(job.phase_seconds),
        counters=dict(job.counters),
    )


# ── the active job ───────────────────────────────────────────────────────────

_LOCK = threading.Lock()
_ACTIVE: Optional[JobTelemetry] = None


def active() -> Optional[JobTelemetry]:
    """The job being recorded, or None outside one (for tests and for callers to skip)."""
    return _ACTIVE


@contextmanager
def job(label: str = "build") -> Iterator[JobTelemetry]:
    """Record every model call and phase for the duration of one build.

    Re-entrant like :func:`studio.memo.build_memo`: an inner ``job`` joins the outer one, so
    a caller that opens it around the whole Generate and an inner step that opens it around
    assembly share one record rather than splitting the evidence in half.
    """
    global _ACTIVE
    with _LOCK:
        existing = _ACTIVE
        if existing is None:
            _ACTIVE = JobTelemetry(label=label)
        current = _ACTIVE
    if existing is not None:
        yield current
        return
    try:
        yield current
    finally:
        with _LOCK:
            _ACTIVE = None
        logger.info("studio telemetry: %s", current.summary().as_line())


@contextmanager
def phase(name: str) -> Iterator[None]:
    """Time one named build phase (``data``, ``authorship``, ``render``…).

    Phases are wall-clock and may nest; each records its own elapsed time under its own
    name, so a nested phase is counted inside its parent rather than subtracted from it.
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started
        with _LOCK:
            if _ACTIVE is not None:
                _ACTIVE.phase_seconds[name] = _ACTIVE.phase_seconds.get(name, 0.0) + elapsed


def record(call: ModelCall) -> None:
    """Append one model call to the running job. A no-op outside a job."""
    with _LOCK:
        if _ACTIVE is not None:
            _ACTIVE.calls.append(call)


def count(name: str, n: int = 1) -> None:
    """Bump a named counter — cache hits, repaired fields, refused sections."""
    with _LOCK:
        if _ACTIVE is not None:
            _ACTIVE.counters[name] = _ACTIVE.counters.get(name, 0) + n


def token_counts(response: object) -> Tuple[int, int]:
    """``(input, output)`` tokens off a LangChain response, or ``(0, 0)``.

    Best-effort by design: the field moved between LangChain versions and a provider is
    free to return none at all, and a missing token count must never be the reason a
    commentary column fails.
    """
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    meta = getattr(response, "response_metadata", None) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {} if isinstance(meta, dict) else {}
    if isinstance(usage, dict):
        return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    return 0, 0
