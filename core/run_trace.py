"""What one chat turn cost: time per step, model calls, and tokens.

The turn already logs a `turn_token_total` line, but only for calls that report
themselves — the claim selector and the narrator invoke their clients directly
and never did, so the most expensive call in a turn (the one that writes the
answer) was missing from its own total. This module measures from the OUTSIDE
instead:

    RunRecorder            one per turn: node timeline + model-call ledger
    UsageCallbackHandler   a LangChain callback attached to the turn's config;
                           every model call in the turn passes through it, so
                           coverage does not depend on each call site remembering

Both are plain Python with no Dash or database import, so the numbers can be
tested without a model. `RunRecorder.finish()` returns a JSON-safe dict that is
stamped on the answer (the footer shows it) and persisted for the operations view
(:mod:`core.store.run_traces`).
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from core.observability import extract_token_usage

#: Nodes whose names say nothing to a reader of the timeline. They still count
#: toward time and tokens; they just do not get a row of their own.
_INTERNAL_NODES = frozenset({"model", "tools", "__start__", "__end__"})


@dataclass
class StepTiming:
    """One named step of the turn, as the reader saw it on the status line."""

    node: str
    label: str
    started_ms: int
    duration_ms: int = 0


@dataclass
class ModelCall:
    """One model call: who made it, on which model, what it cost, how long."""

    node: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    duration_ms: int = 0


@dataclass
class RunRecorder:
    """Collects the timeline and the model calls for ONE turn. Thread-safe.

    Parallel solvers report from worker threads, so every mutation takes the
    lock. `clock` is injectable so tests can drive time deterministically.
    """

    clock: Any = time.perf_counter
    started: float = 0.0
    steps: List[StepTiming] = field(default_factory=list)
    calls: List[ModelCall] = field(default_factory=list)
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    def _now_ms(self) -> int:
        return int((self.clock() - self.started) * 1000)

    def enter(self, node: str, label: str = "") -> None:
        """A node started. Closes the previous step at the same instant."""
        if not node or node in _INTERNAL_NODES:
            return
        with self._lock:
            now = self._now_ms()
            if self.steps and not self.steps[-1].duration_ms:
                self.steps[-1].duration_ms = max(0, now - self.steps[-1].started_ms)
            self.steps.append(StepTiming(node, label or node, now))

    def add_call(self, call: ModelCall) -> None:
        with self._lock:
            self.calls.append(call)

    def finish(self, status: str = "ok") -> Dict[str, Any]:
        """The turn's trace as a JSON-safe dict; closes the open step."""
        with self._lock:
            now = self._now_ms()
            if self.steps and not self.steps[-1].duration_ms:
                self.steps[-1].duration_ms = max(0, now - self.steps[-1].started_ms)
            return build_trace(list(self.steps), list(self.calls), now, status)


def build_trace(steps: List[StepTiming], calls: List[ModelCall],
                elapsed_ms: int, status: str = "ok") -> Dict[str, Any]:
    """Roll steps and calls up into the dict an answer carries. Pure."""
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    by_node: Dict[str, Dict[str, int]] = {}
    for call in calls:
        bucket = by_node.setdefault(call.node or "other",
                                    {"calls": 0, "total_tokens": 0, "duration_ms": 0})
        bucket["calls"] += 1
        bucket["total_tokens"] += call.total_tokens
        bucket["duration_ms"] += call.duration_ms
        for key in totals:
            totals[key] += getattr(call, key)
    return {
        "status": status,
        "elapsed_ms": int(elapsed_ms),
        "llm_calls": len(calls),
        "tokens": totals,
        "models": sorted({c.model for c in calls if c.model}),
        "by_node": by_node,
        "steps": [asdict(step) for step in merge_steps(steps)],
    }


def merge_steps(steps: List[StepTiming]) -> List[StepTiming]:
    """Consecutive steps carrying the same label read as one step.

    Three gate nodes all say "Understanding your question"; a reader sees one
    phase, so the timeline shows one row with their combined time.
    """
    merged: List[StepTiming] = []
    for step in steps:
        if merged and merged[-1].label == step.label:
            merged[-1].duration_ms += step.duration_ms
            continue
        merged.append(StepTiming(step.node, step.label, step.started_ms, step.duration_ms))
    return merged


def _usage_of(response: Any) -> Dict[str, int]:
    """Token usage from an LLMResult, whichever provider shape it arrived in."""
    usage: Dict[str, int] = {}
    for generations in getattr(response, "generations", None) or []:
        for generation in generations or []:
            message = getattr(generation, "message", None)
            if message is not None:
                found = extract_token_usage(message)
                if any(found.values()):
                    for key, value in found.items():
                        usage[key] = usage.get(key, 0) + int(value or 0)
    if not usage:
        output = getattr(response, "llm_output", None) or {}
        raw = output.get("token_usage") or output.get("usage") or {}
        usage = {
            "input_tokens": int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0),
            "output_tokens": int(raw.get("completion_tokens") or raw.get("output_tokens") or 0),
            "total_tokens": int(raw.get("total_tokens") or 0),
            "cached_tokens": 0,
        }
    if usage and not usage.get("total_tokens"):
        usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return usage


def _model_of(serialized: Any, metadata: Dict[str, Any]) -> str:
    name = (metadata or {}).get("ls_model_name")
    if name:
        return str(name)
    kwargs = (serialized or {}).get("kwargs") or {}
    return str(kwargs.get("deployment_name") or kwargs.get("model_name")
               or kwargs.get("model") or "")


class UsageCallbackHandler(BaseCallbackHandler):
    """Records every model call in a turn into a :class:`RunRecorder`.

    Attached to the turn's run config beside the token-stream handler, so it
    inherits the same propagation into nested calls. `langgraph_node` in the
    callback metadata names the node that made the call. Never raises: a meter
    must not be able to fail the turn it is measuring.
    """

    raise_error = False

    def __init__(self, recorder: RunRecorder) -> None:
        self._recorder = recorder
        self._open: Dict[UUID, tuple] = {}
        self._lock = threading.Lock()

    def _start(self, run_id: UUID, serialized: Any, metadata: Optional[Dict[str, Any]]) -> None:
        node = str((metadata or {}).get("langgraph_node") or "")
        with self._lock:
            self._open[run_id] = (node, _model_of(serialized, metadata or {}),
                                  time.perf_counter())

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: UUID,
                            metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        self._start(run_id, serialized, metadata)

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: UUID,
                     metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        self._start(run_id, serialized, metadata)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            node, model, began = self._open.pop(run_id, ("", "", time.perf_counter()))
        usage = _usage_of(response)
        self._recorder.add_call(ModelCall(
            node=node, model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cached_tokens=usage.get("cached_tokens", 0),
            duration_ms=int((time.perf_counter() - began) * 1000),
        ))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            self._open.pop(run_id, None)


# ── Reader-facing formatting ──────────────────────────────────────────────────


def format_tokens(count: Any) -> str:
    """12,345 -> "12.3k"; small counts stay whole."""
    try:
        value = int(count or 0)
    except (TypeError, ValueError):
        return "0"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def format_duration(ms: Any) -> str:
    """840 -> "0.8s"; 75_000 -> "1m 15s"."""
    try:
        value = max(0, int(ms or 0))
    except (TypeError, ValueError):
        return "0s"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m {secs:02d}s"
