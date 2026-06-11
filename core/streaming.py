"""Token-streaming + cooperative-cancel callback handler for chat turns.

A single `TokenStreamHandler` is attached to the main graph's run config (see
`LangGraph.stream_workflow`). LangChain propagates the active run config — and
thus this handler — down to every nested LLM call in the turn, including the
analyst subgraph's writer, so we can:

  1. forward the FINAL-ANSWER tokens to the UI as they are generated, and
  2. abort an in-flight call the instant the user hits Stop.

Only calls tagged ``final_answer`` stream their tokens to the sink; the analyst
writer tags its call with ``.with_config(tags=["final_answer"])``. Every other
LLM call in the turn (planner, solvers, routers) is untagged and stays silent —
so the live draft shows the answer being written, not the model's scratch work.

Cancellation is cooperative but effectively immediate: the handler raises
`JobCancelled` from inside the callback, which unwinds the streaming generator
mid-token instead of waiting for the slow node to finish. ``raise_error = True``
is ESSENTIAL — without it LangChain catches-and-logs handler exceptions, and Stop
would do nothing until the next node boundary (the old behaviour).
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional, Sequence

from langchain_core.callbacks import BaseCallbackHandler

_FINAL_ANSWER_TAG = "final_answer"


class JobCancelled(Exception):
    """Raised inside the callback to abort an in-flight LLM call on Stop."""


class TokenStreamHandler(BaseCallbackHandler):
    """Stream final-answer tokens to a sink and abort the call on cancel.

    `cancel` is the job's ``threading.Event``; `on_token` is a thread-safe sink
    (``Job.append_partial``). Calls whose run tags include `stream_tag` have each
    token forwarded; all calls are aborted the moment `cancel` is set.
    """

    # Make LangChain re-raise our JobCancelled instead of logging-and-swallowing,
    # so a Stop actually aborts the call in progress.
    raise_error = True

    def __init__(
        self,
        cancel: threading.Event,
        on_token: Callable[[str], None],
        *,
        stream_tag: str = _FINAL_ANSWER_TAG,
    ) -> None:
        self._cancel = cancel
        self._on_token = on_token
        self._stream_tag = stream_tag

    def _check_cancel(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise JobCancelled()

    # Abort the NEXT call early (covers the non-streamed solver/planner loop, so a
    # Stop doesn't have to wait for a multi-step solver to grind to its next node).
    def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        self._check_cancel()

    def on_llm_start(self, serialized: Any, prompts: Any, **kwargs: Any) -> None:
        self._check_cancel()

    # Abort the CURRENT call mid-flight, and forward final-answer tokens live.
    def on_llm_new_token(
        self,
        token: str,
        *,
        tags: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> None:
        self._check_cancel()
        if token and tags and self._stream_tag in tags:
            self._on_token(token)
