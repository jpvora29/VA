"""Every model call the MoM pipeline makes, behind one small interface.

The pipeline depends on :class:`JsonCaller` — "give me a prompt, get a dict" — and
never on Azure, LangChain or a deployment name. That is what lets the whole pipeline
be tested without credentials: pass a stub caller.

The credentials themselves come from ``core.llm.clients``, so MoM shares the
application's ``.env`` rather than carrying a second, hard-coded key as the
standalone version did.
"""
from __future__ import annotations

import json
import time
from typing import Any, Protocol

from logger import get_logger
from mom.run_log import RunLog

log = get_logger(__name__)


class JsonCaller(Protocol):
    """Send a prompt, get parsed JSON back."""

    def __call__(self, prompt: str, *, label: str = "", phase: str = "unknown") -> dict: ...


class LlmJsonCaller:
    """A :class:`JsonCaller` backed by a LangChain chat client in JSON mode.

    Token usage lands in ``run_log``; the pipeline itself never sees a token count.
    """

    def __init__(self, client: Any, run_log: RunLog) -> None:
        self._client = client
        self._run_log = run_log

    def __call__(self, prompt: str, *, label: str = "", phase: str = "unknown") -> dict:
        index = self._run_log.next_call_index()
        tag = f"[LLM {index}]{f' {label}' if label else ''}"

        started = time.perf_counter()
        response = self._client.invoke(prompt)
        duration = time.perf_counter() - started

        self._record(response, index=index, label=label, phase=phase, duration=duration)

        content = (response.content or "").strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{tag} JSON parse failed: {exc}\nRaw: {content[:500]}") from exc

    def _record(self, response, *, index: int, label: str, phase: str, duration: float) -> None:
        usage = getattr(response, "usage_metadata", None) or {}
        details = usage.get("output_token_details") or {}
        reasoning = details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0
        self._run_log.record_call(
            call_index=index,
            label=label,
            phase=phase,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            reasoning_tokens=reasoning,
            duration_s=duration,
        )
        log.debug(
            "mom llm call %s label=%s phase=%s in=%s out=%s %.2fs",
            index, label, phase, usage.get("input_tokens", 0),
            usage.get("output_tokens", 0), duration,
        )


def make_json_caller(run_log: RunLog, tier: str = "balanced") -> JsonCaller:
    """The production caller: the application's Azure client, pinned to JSON output."""
    from core.llm.clients import make_client

    client = make_client(tier).bind(response_format={"type": "json_object"})
    return LlmJsonCaller(client, run_log)
