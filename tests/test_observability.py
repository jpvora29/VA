"""Tests for trace-context propagation and log redaction in core.observability.

Run:  pytest tests/test_observability.py -q -o pythonpath=.
"""
from __future__ import annotations

import logging

from core.observability import (
    accumulate_token_usage,
    bind_trace,
    get_trace_fields,
    log_event,
    normalize_dspy_usage,
    record_token_usage,
    redact_text,
    redact_value,
    turn_context,
)

logger = logging.getLogger("test.observability")


def _fields(record: logging.LogRecord) -> dict:
    return getattr(record, "event_fields", {})


# ── trace context ───────────────────────────────────────────────────────────


def test_turn_context_stamps_and_resets():
    assert get_trace_fields() == {}
    with turn_context(trace_id="abc123", thread_id="t-1") as tid:
        assert tid == "abc123"
        f = get_trace_fields()
        assert f["trace_id"] == "abc123" and f["thread_id"] == "t-1"
    # Restored after the turn — no leakage across turns/threads.
    assert get_trace_fields() == {}


def test_log_event_auto_injects_trace_id(caplog):
    with caplog.at_level(logging.DEBUG, logger="test.observability"):
        with turn_context(trace_id="trace-xyz", thread_id="thread-9"):
            log_event(logger, "some_event", node="planner")
    rec = next(r for r in caplog.records if _fields(r).get("event") == "some_event")
    fields = _fields(rec)
    assert fields["trace_id"] == "trace-xyz"
    assert fields["thread_id"] == "thread-9"
    assert fields["node"] == "planner"


def test_log_event_outside_turn_has_no_trace(caplog):
    with caplog.at_level(logging.DEBUG, logger="test.observability"):
        log_event(logger, "bare_event")
    rec = next(r for r in caplog.records if _fields(r).get("event") == "bare_event")
    assert "trace_id" not in _fields(rec)


def test_bind_trace_merges_and_token_resets():
    token = bind_trace(trace_id="t", extra="x")
    try:
        assert get_trace_fields()["extra"] == "x"
    finally:
        import core.observability as obs

        obs._trace_ctx.reset(token)
    assert get_trace_fields() == {}


# ── token accounting ─────────────────────────────────────────────────────────


def test_normalize_dspy_usage_sums_across_lms():
    out = normalize_dspy_usage(
        {
            "azure/gpt-41-mini": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 80},
            },
            "azure/other": {
                "prompt_tokens": 5,
                "completion_tokens": 1,
                "total_tokens": 6,
            },
        }
    )
    assert out["input_tokens"] == 105
    assert out["output_tokens"] == 21
    assert out["total_tokens"] == 126
    assert out["cached_tokens"] == 80


def test_normalize_dspy_usage_empty_is_all_none():
    assert normalize_dspy_usage({}) == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cached_tokens": None,
    }


def test_turn_emits_token_total_with_per_agent_breakdown(caplog):
    with caplog.at_level(logging.INFO, logger="core.observability"):
        with turn_context(trace_id="tt-1", thread_id="chat-1"):
            record_token_usage(
                {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                label="context_filler_agent",
            )
            record_token_usage(
                {"input_tokens": 30, "output_tokens": 6, "total_tokens": 36},
                label="rephraser_agent",
            )
    rec = next(
        r for r in caplog.records if _fields(r).get("event") == "turn_token_total"
    )
    fields = _fields(rec)
    assert fields["trace_id"] == "tt-1" and fields["thread_id"] == "chat-1"
    assert fields["llm_calls"] == 2
    assert fields["token_total"]["total_tokens"] == 50
    assert fields["by_agent"]["context_filler_agent"]["total_tokens"] == 14
    assert fields["by_agent"]["rephraser_agent"]["calls"] == 1


def test_accumulate_outside_turn_is_noop():
    # Must not raise when there is no active turn accumulator.
    accumulate_token_usage({"input_tokens": 5, "total_tokens": 5}, "stray")


def test_no_token_total_when_no_usage(caplog):
    with caplog.at_level(logging.INFO, logger="core.observability"):
        with turn_context(trace_id="tt-2"):
            log_event(logging.getLogger("core.observability"), "noop")
    assert not any(
        _fields(r).get("event") == "turn_token_total" for r in caplog.records
    )


# ── redaction ───────────────────────────────────────────────────────────────


def test_redact_text_scrubs_email_and_secret():
    out = redact_text("contact jash@example.com api_key=sk-supersecret123")
    assert "jash@example.com" not in out
    assert "sk-supersecret123" not in out
    assert "[REDACTED_EMAIL]" in out


def test_redact_value_nested():
    payload = {
        "api_key": "sk-123",
        "user_email": "a@b.com",
        "rows": [{"x": 1}, {"x": 2}, {"x": 3}],  # bulky payload key → summarized
        "count": 7,  # structured metadata passes through
    }
    out = redact_value(payload)
    assert out["api_key"] == "[REDACTED]"
    assert "a@b.com" not in str(out["user_email"])
    assert out["rows"]["type"] in ("list", "tuple")  # summarized, not raw rows
    assert out["count"] == 7


def test_log_event_redacts_string_field_but_keeps_metadata_list(caplog):
    with caplog.at_level(logging.DEBUG, logger="test.observability"):
        log_event(
            logger,
            "redact_event",
            error="failure for user me@corp.com",  # string → scrubbed
            matched=["a", "b", "c"],  # metadata list → preserved
        )
    fields = _fields(next(r for r in caplog.records if _fields(r).get("event") == "redact_event"))
    assert "me@corp.com" not in fields["error"]
    assert fields["matched"] == ["a", "b", "c"]
