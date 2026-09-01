"""Per-run token and timing accounting.

The standalone pipeline kept one module-level ``logger`` singleton, which is fine for
a process that runs once and exits and wrong inside a long-lived app: two MoM runs
would have added their tokens into the same totals. A :class:`RunLog` is created per
run and handed to the phases that need it, so the numbers belong to one run.

Rendering the log as a workbook is :mod:`mom.run_log_excel`'s job — this module only
counts.
"""
from __future__ import annotations

import datetime
import threading
import time
from typing import Dict, List

from pydantic import BaseModel


class TokenUsage(BaseModel):
    """Token counts for a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0  # thinking tokens (o-series / gpt-5 models)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class CallRecord(BaseModel):
    """One completed LLM API call."""

    call_index: int
    label: str
    phase: str
    usage: TokenUsage
    duration_s: float
    timestamp: str  # ISO-8601


class PhaseTokenSummary(BaseModel):
    """Aggregated token usage for one pipeline phase."""

    phase: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    wall_time_s: float = 0.0


class RunSummary(BaseModel):
    """The serialisable run report."""

    run_id: str
    total_duration_s: float
    total_llm_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_reasoning_tokens: int
    total_tokens: int
    phase_breakdown: List[PhaseTokenSummary]
    calls: List[CallRecord]


class RunLog:
    """Wall-clock time per phase and token usage per call, for ONE run.

    Slide tagging fans out across a thread pool, so ``record_call`` is called from
    several threads at once and takes a lock.
    """

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id
        self._started = time.time()
        self._calls: List[CallRecord] = []
        self._phase_times: Dict[str, float] = {}
        self._phase_start: Dict[str, float] = {}
        self._lock = threading.Lock()

    # ── timing ────────────────────────────────────────────────────────────────

    def start_phase(self, phase: str) -> None:
        self._phase_start[phase] = time.perf_counter()

    def end_phase(self, phase: str) -> None:
        if phase in self._phase_start:
            elapsed = time.perf_counter() - self._phase_start.pop(phase)
            self._phase_times[phase] = round(elapsed, 2)

    # ── calls ─────────────────────────────────────────────────────────────────

    def next_call_index(self) -> int:
        """A 1-based index for the next call, unique across the tagging threads."""
        with self._lock:
            return len(self._calls) + 1

    def record_call(
        self,
        *,
        call_index: int,
        label: str,
        phase: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
        duration_s: float,
    ) -> None:
        record = CallRecord(
            call_index=call_index,
            label=label,
            phase=phase,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
            ),
            duration_s=round(duration_s, 3),
            timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        )
        with self._lock:
            self._calls.append(record)

    # ── report ────────────────────────────────────────────────────────────────

    def summary(self) -> RunSummary:
        with self._lock:
            calls = list(self._calls)

        by_phase: Dict[str, PhaseTokenSummary] = {}
        for call in calls:
            phase = by_phase.setdefault(call.phase, PhaseTokenSummary(phase=call.phase))
            phase.calls += 1
            phase.input_tokens += call.usage.input_tokens
            phase.output_tokens += call.usage.output_tokens
            phase.reasoning_tokens += call.usage.reasoning_tokens
            phase.total_tokens += call.usage.total_tokens

        # Phases that ran without an LLM call (PPT extraction) still deserve a row.
        ordered = dict.fromkeys(list(self._phase_times) + list(by_phase))
        breakdown = []
        for name in ordered:
            phase = by_phase.get(name, PhaseTokenSummary(phase=name))
            phase.wall_time_s = self._phase_times.get(name, 0.0)
            breakdown.append(phase)

        total_in = sum(c.usage.input_tokens for c in calls)
        total_out = sum(c.usage.output_tokens for c in calls)
        return RunSummary(
            run_id=self.run_id,
            total_duration_s=round(time.time() - self._started, 2),
            total_llm_calls=len(calls),
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_reasoning_tokens=sum(c.usage.reasoning_tokens for c in calls),
            total_tokens=total_in + total_out,
            phase_breakdown=breakdown,
            calls=calls,
        )
