import contextvars
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional

SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|credential|authorization)\b\s*[:=]\s*['\"]?([^'\"\s,;]+)"
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SQL_LITERAL_PATTERN = re.compile(
    r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\b\d+(?:\.\d+)?\b)"
)
SQL_COMMENT_PATTERN = re.compile(r"(--[^\n\r]*|/\*.*?\*/)", re.DOTALL)
SQL_TABLE_PATTERN = re.compile(
    r"\b(?:from|join)\s+([`\"\[]?[A-Za-z_][\w.]*[`\"\]]?)", re.IGNORECASE
)
SQL_SELECT_PATTERN = re.compile(
    r"\bselect\b\s+(.*?)\s+\bfrom\b", re.IGNORECASE | re.DOTALL
)
UNSAFE_SQL_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|attach|detach|pragma|vacuum|replace|create)\b",
    re.IGNORECASE,
)

MAX_TEXT_LENGTH = int(os.getenv("LOG_MAX_TEXT_LENGTH", "300"))
LOG_RAW_SQL = os.getenv("LOG_RAW_SQL", "false").lower() == "true"
LOG_RAW_PROMPTS = os.getenv("LOG_RAW_PROMPTS", "false").lower() == "true"
LOG_REDACTION_ENABLED = os.getenv("LOG_REDACTION_ENABLED", "true").lower() != "false"

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "event_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = getattr(record, "event_fields", {})
        if not fields:
            return base
        safe_fields = {key: value for key, value in fields.items()}
        return f"{base} | {json.dumps(safe_fields, default=str, sort_keys=True)}"


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "text").lower()
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level, logging.INFO))
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


# ── Turn-scoped trace context ────────────────────────────────────────────────
#
# A single user turn fans out across many nodes (routing → planner → SQL →
# solvers → response → charts). Threading a request id through every function
# signature would touch hundreds of call sites; a ContextVar lets `log_event`
# stamp every line with the same `trace_id` (and `thread_id`) automatically. Set
# it once at the turn boundary via `turn_context`. LangGraph copies the context
# into node tasks, so node and (best-effort) parallel-solver logs inherit it too.

_trace_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "trace_ctx", default={}
)


def get_trace_fields() -> dict[str, Any]:
    """Current turn-scoped fields ({} outside a turn)."""
    return dict(_trace_ctx.get())


def bind_trace(**fields: Any) -> contextvars.Token:
    """Merge fields into the trace context; returns a token for `reset`."""
    merged = dict(_trace_ctx.get())
    merged.update({k: v for k, v in fields.items() if v is not None})
    return _trace_ctx.set(merged)


# ── Turn-scoped token accounting ─────────────────────────────────────────────
#
# Every LM call in a turn reports its usage through `record_token_usage`, which
# both logs a per-call `llm_token_usage` line AND folds the numbers into a
# turn-scoped accumulator. At the turn boundary `turn_context` flushes one
# `turn_token_total` line carrying the turn total plus a per-agent breakdown, so
# cost is answerable at three grains:
#   - per agent  → `turn_token_total.by_agent[<label>]`, or any `llm_token_usage`
#   - per turn   → one `turn_token_total` per `trace_id`
#   - per chat   → sum `turn_token_total` over a `thread_id`
#
# The accumulator object is stored in a ContextVar but mutated IN PLACE under a
# lock. LangGraph copies the context (hence the same object reference) into
# parallel solver threads, so their usage lands in the parent turn's totals too.

_USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens", "cached_tokens")


class _TokenAccumulator:
    """Thread-safe running total of token usage for a single turn."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.total: dict[str, int] = {key: 0 for key in _USAGE_KEYS}
        self.by_agent: dict[str, dict[str, int]] = {}

    def add(self, usage: dict[str, Any], label: str) -> None:
        agent = label or "unknown"
        with self._lock:
            self.calls += 1
            bucket = self.by_agent.setdefault(
                agent, {key: 0 for key in _USAGE_KEYS} | {"calls": 0}
            )
            bucket["calls"] += 1
            for key in _USAGE_KEYS:
                value = usage.get(key) or 0
                self.total[key] += value
                bucket[key] += value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls,
                "total": dict(self.total),
                "by_agent": {k: dict(v) for k, v in self.by_agent.items()},
            }


_token_acc: contextvars.ContextVar[Optional[_TokenAccumulator]] = (
    contextvars.ContextVar("token_acc", default=None)
)

# ── Turn sink (diagnostic/test tap) ──────────────────────────────────────────
#
# An optional callable invoked once at each turn's close with the turn's rollup
# ({trace_id, fields, token}). The golden-query harness registers one to read
# per-turn / per-agent token totals directly instead of scraping log lines. No
# behavior change when unset (the common case); a sink that raises is swallowed,
# because a diagnostic tap must never break a turn.
_turn_sink: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "turn_sink", default=None
)


def set_turn_sink(sink: Any) -> contextvars.Token:
    """Register a turn-close callback; returns a token for `reset_turn_sink`."""
    return _turn_sink.set(sink)


def reset_turn_sink(token: contextvars.Token) -> None:
    _turn_sink.reset(token)


_usage_logger = logging.getLogger(__name__)


def normalize_dspy_usage(total_by_lm: dict[str, Any]) -> dict[str, Optional[int]]:
    """Flatten dspy's `UsageTracker.get_total_tokens()` to our standard shape.

    dspy returns `{lm_name: {prompt_tokens, completion_tokens, total_tokens,
    prompt_tokens_details: {cached_tokens, ...}, ...}}`. Sum across LMs into the
    same `{input,output,total,cached}_tokens` keys `extract_token_usage` emits.
    """
    out = {key: 0 for key in _USAGE_KEYS}
    seen = False
    for entry in (total_by_lm or {}).values():
        if not isinstance(entry, dict):
            continue
        seen = True
        out["input_tokens"] += entry.get("prompt_tokens") or 0
        out["output_tokens"] += entry.get("completion_tokens") or 0
        out["total_tokens"] += entry.get("total_tokens") or 0
        details = entry.get("prompt_tokens_details")
        if isinstance(details, dict):
            out["cached_tokens"] += details.get("cached_tokens") or 0
    return out if seen else {key: None for key in _USAGE_KEYS}


def accumulate_token_usage(usage: dict[str, Any], label: str) -> None:
    """Fold one call's usage into the active turn accumulator (no-op outside a turn)."""
    acc = _token_acc.get()
    if acc is not None and any(usage.get(key) for key in _USAGE_KEYS):
        acc.add(usage, label)


def record_token_usage(
    usage: dict[str, Any], label: str = "", node: Optional[str] = None
) -> None:
    """Log a per-call `llm_token_usage` line and accumulate it into the turn total.

    Single entry point so every LM call site (LangChain or dspy) lands in both
    the per-call log and the turn rollup.
    """
    if not any(usage.get(key) is not None for key in _USAGE_KEYS):
        return
    log_event(
        _usage_logger, "llm_token_usage", label=label, node=node, token_usage=usage
    )
    accumulate_token_usage(usage, label)


@contextmanager
def turn_context(trace_id: Optional[str] = None, **fields: Any) -> Iterator[str]:
    """Bind a `trace_id` (+ any fields) for the duration of one turn.

    Every `log_event` emitted while this is active carries the bound fields. The
    context is restored on exit so threads/turns never leak ids into each other.
    A fresh token accumulator is installed for the turn and flushed as a single
    `turn_token_total` line on exit.
    """
    tid = trace_id or new_request_id()
    token = bind_trace(trace_id=tid, **fields)
    acc = _TokenAccumulator()
    acc_token = _token_acc.set(acc)
    try:
        yield tid
    finally:
        snap = acc.snapshot()
        if snap["calls"]:
            log_event(
                _usage_logger,
                "turn_token_total",
                llm_calls=snap["calls"],
                token_total=snap["total"],
                by_agent=snap["by_agent"],
            )
        sink = _turn_sink.get()
        if sink is not None:
            try:
                sink({"trace_id": tid, "fields": dict(fields), "token": snap})
            except Exception:  # noqa: BLE001 - a tap must never break a turn
                pass
        _token_acc.reset(acc_token)
        _trace_ctx.reset(token)


# Field names whose VALUES may carry free-form user/model content worth deep
# redaction (vs. structured metadata, which is left intact for observability).
_SENSITIVE_FIELDS = frozenset(
    {
        "messages", "prompt", "raw_prompt", "raw_sql", "rows", "query_result",
        "payload", "state", "answer", "response", "content",
    }
)


def hash_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def redact_text(value: str, *, allow_prompt: bool = False) -> str:
    if not LOG_REDACTION_ENABLED:
        return value
    if not allow_prompt and not LOG_RAW_PROMPTS and len(value) > MAX_TEXT_LENGTH:
        value = value[:MAX_TEXT_LENGTH] + "...[truncated]"
    value = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    value = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
    return value


_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|credential|authorization)"
)


def redact_value(value: Any) -> Any:
    """Recursively redact a (possibly nested) value for safe logging.

    - strings        → secret/email scrub + length cap (`redact_text`)
    - secret-named    → replaced with `[REDACTED]` when the value is a STRING.
      dict keys         Numeric values are never secrets (a key like
                        `total_tokens` is a count, not a credential), so they
                        pass through; dict/list values recurse so nested strings
                        are still scrubbed.
    - bulky payload   → summarized to {type, count/keys/...} (`summarize_payload`)
      keys (messages, prompt, rows, …)
    - long lists      → collapsed to {type, count, sample[:3]}
    Returns the value unchanged when redaction is disabled.
    """
    if not LOG_REDACTION_ENABLED:
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEY_PATTERN.search(key_text) and isinstance(item, str):
                redacted[key] = "[REDACTED]"
            elif key_text.lower() in _SENSITIVE_FIELDS:
                redacted[key] = summarize_payload(item)
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, (list, tuple)):
        if len(value) > 10:
            return {
                "type": type(value).__name__,
                "count": len(value),
                "sample": [redact_value(item) for item in value[:3]],
            }
        return [redact_value(item) for item in value]
    return value


def _redact_field(key: str, value: Any) -> Any:
    """Per-field redaction for `log_event`.

    Strings are always scrubbed/capped; sensitive-named fields get deep
    redaction; everything else (structured metadata: counts, name lists, flags)
    passes through untouched so observability detail is preserved.
    """
    if not LOG_REDACTION_ENABLED:
        return value
    if isinstance(value, str):
        return redact_text(value)
    if key.lower() in _SENSITIVE_FIELDS or _SECRET_KEY_PATTERN.search(key):
        return redact_value(value)
    return value


def summarize_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, (list, tuple)):
        return {"type": type(value).__name__, "count": len(value)}
    if isinstance(value, dict):
        return {"type": "dict", "keys": sorted(str(key) for key in value.keys())[:20]}
    if isinstance(value, str):
        return {"type": "str", "length": len(value), "hash": hash_text(value)}
    return {"type": type(value).__name__}


def sanitize_sql(sql: str) -> str:
    without_comments = SQL_COMMENT_PATTERN.sub(" ", sql or "")
    normalized = re.sub(r"\s+", " ", without_comments).strip()
    return SQL_LITERAL_PATTERN.sub("?", normalized)


def sql_metadata(
    sql: str, *, row_count: Optional[int] = None, duration_ms: Optional[float] = None
) -> dict[str, Any]:
    sql = sql or ""
    stripped = sql.strip()
    without_comments = SQL_COMMENT_PATTERN.sub(" ", stripped)
    statement_parts = [
        part.strip() for part in without_comments.split(";") if part.strip()
    ]
    query_type_match = re.match(r"^\s*([A-Za-z]+)", without_comments)
    query_type = query_type_match.group(1).upper() if query_type_match else "UNKNOWN"

    tables = []
    for table in SQL_TABLE_PATTERN.findall(without_comments):
        clean_table = table.strip('`"[]')
        if clean_table not in tables:
            tables.append(clean_table)

    selected_columns = []
    select_match = SQL_SELECT_PATTERN.search(without_comments)
    if select_match:
        raw_columns = select_match.group(1)
        if "*" in raw_columns:
            selected_columns = ["*"]
        else:
            selected_columns = [
                SQL_LITERAL_PATTERN.sub("?", col.strip())[:80]
                for col in raw_columns.split(",")
                if col.strip()
            ][:20]

    metadata: dict[str, Any] = {
        "query_type": query_type,
        "statement_count": len(statement_parts),
        "tables": tables[:20],
        "selected_columns": selected_columns,
        "has_limit": bool(re.search(r"\blimit\b", without_comments, re.IGNORECASE)),
        "has_comments": bool(SQL_COMMENT_PATTERN.search(stripped)),
        "unsafe_keywords": sorted(
            {
                match.group(1).upper()
                for match in UNSAFE_SQL_PATTERN.finditer(without_comments)
            }
        ),
        "sql_hash": hash_text(stripped),
    }
    if row_count is not None:
        metadata["row_count"] = row_count
    if duration_ms is not None:
        metadata["duration_ms"] = round(duration_ms, 2)
    if LOG_RAW_SQL:
        metadata["sanitized_sql"] = sanitize_sql(stripped)
    return metadata


def extract_token_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None) or {}
    response_metadata = getattr(response, "response_metadata", None) or {}
    token_usage = (
        response_metadata.get("token_usage") or response_metadata.get("usage") or {}
    )
    prompt_details = (
        usage.get("input_token_details")
        or usage.get("prompt_tokens_details")
        or token_usage.get("prompt_tokens_details")
        or {}
    )
    return {
        "input_tokens": usage.get("input_tokens") or token_usage.get("prompt_tokens"),
        "output_tokens": usage.get("output_tokens")
        or token_usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens") or token_usage.get("total_tokens"),
        "cached_tokens": prompt_details.get("cache_read")
        or prompt_details.get("cached_tokens"),
    }


def log_event(
    logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any
) -> None:
    """Emit a structured log line.

    Automatically stamps the active turn's trace fields (`trace_id`, `thread_id`,
    …) from the ContextVar and redacts each field value, so call sites never have
    to pass an id or worry about leaking secrets/PII into logs.
    """
    event_fields: dict[str, Any] = {**get_trace_fields(), "event": event}
    for key, value in fields.items():
        event_fields[key] = _redact_field(key, value)
    logger.log(level, event, extra={"event_fields": event_fields})


@contextmanager
def latency_timer() -> Iterator[dict[str, float]]:
    started = time.perf_counter()
    timing: dict[str, float] = {}
    try:
        yield timing
    finally:
        timing["duration_ms"] = (time.perf_counter() - started) * 1000


def legacy_print_logger(logger: logging.Logger, *, event: str = "legacy_print"):
    def _log_print(*args: Any, **kwargs: Any) -> None:
        message = " ".join(str(arg) for arg in args)
        log_event(logger, event, logging.DEBUG, message=message)

    return _log_print
