"""Step pipelines — the one shape every Studio build reads in.

A pipeline is an ordered list of named steps over one shared context object. That
is all. The point is not abstraction, it is *debuggability*: instead of a call
chain where each function quietly calls the next, a build is a flat sequence you
can print, time, and break into.

    pipeline = (
        PipelineBuilder("fill_template")
        .step("write_values", write_values)
        .step("fill_charts", fill_charts, critical=False)
        .build()
    )
    run = pipeline.run(context)          # ctx mutated in place, run.trace explains it

Two things every step gets:

* **A name.** It goes in the log line and in the exception message, so a failure
  says *which* step failed before you open a stack trace.
* **A criticality.** ``critical=True`` (the default) lets the error out — the
  build is wrong without this step. ``critical=False`` logs it and carries on —
  the step is an enrichment, and a deck missing one chart beats no deck at all.
  This is the ``try/except … logger.warning`` that used to be copied around
  every best-effort call, written once.

Rules of the shape, so pipelines stay readable:

* A step takes the context and returns ``None``; it works on the context.
* A step never calls another step. Ordering lives in the pipeline, nowhere else.
* A step is a plain module-level function, so it is callable on its own in a test.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Generic, List, Optional, Sequence, TypeVar

from logger import get_logger

logger = get_logger(__name__)

C = TypeVar("C")

#: What a step does: act on the shared context.
StepFn = Callable[[C], None]


@dataclass(frozen=True)
class Step(Generic[C]):
    """One named unit of work."""

    name: str
    run: StepFn
    #: False → a failure is logged and the pipeline continues (an enrichment step).
    critical: bool = True


@dataclass(frozen=True)
class StepResult:
    """What one step did, for the log and for tests."""

    name: str
    seconds: float
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class PipelineRun(Generic[C]):
    """The finished run: the context it produced and the trace of how."""

    context: C
    trace: List[StepResult] = field(default_factory=list)

    @property
    def failed(self) -> List[StepResult]:
        return [r for r in self.trace if not r.ok]

    def summary(self) -> str:
        """One line per step — paste it into a bug report."""
        return "\n".join(
            f"{r.name:<28} {r.seconds * 1000:7.0f} ms  {r.error or 'ok'}" for r in self.trace
        )


class StepFailed(RuntimeError):
    """A critical step raised. Says which step, keeps the original as ``__cause__``."""

    def __init__(self, pipeline: str, step: str, cause: BaseException):
        super().__init__(f"{pipeline}: step {step!r} failed: {cause}")
        self.pipeline = pipeline
        self.step = step


@dataclass(frozen=True)
class Pipeline(Generic[C]):
    """An ordered list of named steps, run against one context."""

    name: str
    steps: Sequence[Step]

    def run(self, context: C) -> PipelineRun[C]:
        """Run every step in order and return the context with its trace."""
        run: PipelineRun[C] = PipelineRun(context=context)
        for step in self.steps:
            run.trace.append(self._run_step(step, context))
        return run

    def _run_step(self, step: Step, context: C) -> StepResult:
        """One step, timed, with its failure handled per its criticality."""
        started = time.perf_counter()
        try:
            step.run(context)
        except Exception as exc:  # noqa: BLE001 — criticality decides what happens next
            elapsed = time.perf_counter() - started
            if step.critical:
                raise StepFailed(self.name, step.name, exc) from exc
            logger.warning("%s: step %r skipped — %s", self.name, step.name, exc)
            return StepResult(step.name, elapsed, error=str(exc))
        elapsed = time.perf_counter() - started
        logger.debug("%s: step %r in %.0f ms", self.name, step.name, elapsed * 1000)
        return StepResult(step.name, elapsed)

    def step_names(self) -> List[str]:
        return [s.name for s in self.steps]


class PipelineBuilder(Generic[C]):
    """Builds a :class:`Pipeline` one named step at a time.

    Chainable purely so the declaration reads as the sequence it describes; the
    builder holds no other state and produces an immutable pipeline.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._steps: List[Step] = []

    def step(self, name: str, run: StepFn, *, critical: bool = True) -> "PipelineBuilder[C]":
        """Append one step. ``critical=False`` → log a failure and carry on."""
        self._steps.append(Step(name=name, run=run, critical=critical))
        return self

    def optional(self, name: str, run: StepFn) -> "PipelineBuilder[C]":
        """``step(..., critical=False)`` — an enrichment that may fail."""
        return self.step(name, run, critical=False)

    def build(self) -> Pipeline[C]:
        return Pipeline(name=self._name, steps=tuple(self._steps))
