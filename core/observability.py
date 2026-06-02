import hashlib
import json
import logging
import os
import re
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


# def redact_value(value: Any) -> Any:
#     if not LOG_REDACTION_ENABLED:
#         return value
#     if isinstance(value, str):
#         return redact_text(value)
#     if isinstance(value, dict):
#         redacted: dict[str, Any] = {}
#         for key, item in value.items():
#             key_text = str(key)
#             if re.search(
#                 r"(?i)(api[_-]?key|secret|token|password|credential|authorization)",
#                 key_text,
#             ):
#                 redacted[key] = "[REDACTED]"
#             elif key_text.lower() in {
#                 "messages",
#                 "prompt",
#                 "raw_prompt",
#                 "raw_sql",
#                 "rows",
#                 "query_result",
#             }:
#                 redacted[key] = summarize_payload(item)
#             else:
#                 redacted[key] = redact_value(item)
#         return redacted
#     if isinstance(value, (list, tuple)):
#         if len(value) > 10:
#             return {
#                 "type": type(value).__name__,
#                 "count": len(value),
#                 "sample": [redact_value(item) for item in value[:3]],
#             }
#         return [redact_value(item) for item in value]
#     return value


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
    logger.log(level, event, extra={"event_fields": {"event": event, **fields}})


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
