"""Tests for the analyst solver middleware (credential-free).

These avoid importing `core.agents.analyst.common` (which constructs an Azure
client at import time). The middleware module itself has no such dependency, so
the observability hook and the middleware factory can be tested directly.

Run:  pytest tests/test_solver_middleware.py -q -o pythonpath=.
"""
from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from core.agents.analyst.middleware import (
    ModelRetryMiddleware,
    SolverObservabilityMiddleware,
    SummarizationMiddleware,
    _TRANSIENT_MODEL_ERRORS,
    build_solver_middleware,
)


def test_after_model_logs_and_returns_none(caplog):
    mw = SolverObservabilityMiddleware(flow="gpr", lens="peer_benchmark")
    msg = AIMessage(
        content="",
        tool_calls=[{"name": "run_sql", "args": {}, "id": "1"}],
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    with caplog.at_level("DEBUG"):
        result = mw.after_model({"messages": [msg]}, runtime=None)
    assert result is None  # observability is read-only
    assert any("analyst_model_step" in r.getMessage() for r in caplog.records)


def test_after_model_handles_empty_state():
    mw = SolverObservabilityMiddleware()
    assert mw.after_model({}, runtime=None) is None
    assert mw.after_model({"messages": []}, runtime=None) is None


def test_build_solver_middleware_stack():
    model = FakeListChatModel(responses=["ok"])
    stack = build_solver_middleware(model, flow="survey", lens="trend")
    assert len(stack) == 3
    # Retry outermost, then observability, then summarization.
    assert isinstance(stack[0], ModelRetryMiddleware)
    assert isinstance(stack[1], SolverObservabilityMiddleware)
    assert isinstance(stack[2], SummarizationMiddleware)


def test_model_retry_scoped_to_transient_errors():
    # Auth/validation errors must NOT be in the retry set; transient ones must be.
    names = {e.__name__ for e in _TRANSIENT_MODEL_ERRORS}
    assert "RateLimitError" in names or "TimeoutError" in names
    assert "AuthenticationError" not in names
    assert Exception not in _TRANSIENT_MODEL_ERRORS  # never blanket-retry
