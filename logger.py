from __future__ import annotations

import json
import logging
import os

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# --- Custom theme ---
CUSTOM_THEME = Theme(
    {
        "info": "bold cyan",
        "warning": "bold yellow",
        "error": "bold red",
        "critical": "bold white on red",
        "success": "bold green",
        "pipeline": "bold magenta",  # for pipeline stage logs
        "config": "bold blue",  # for config load logs
    }
)

console = Console(theme=CUSTOM_THEME)

# Third-party loggers that flood the terminal with per-request / internal chatter.
# Pinned to WARNING so our own INFO logs stay readable.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "openai",
    "anthropic",
    "urllib3",
    "requests",
    "langchain",
    "langchain_core",
    "langgraph",
    "dspy",
    "LiteLLM",
    "litellm",
    "asyncio",
    "sqlalchemy.engine",
    "watchdog",
    "werkzeug",
    "matplotlib",
    "PIL",
)

_CONFIGURED = False


class EventFieldFormatter(logging.Formatter):
    """Render `log_event`'s structured ``event_fields`` compactly after the message.

    Without this, the previous ``%(message)s`` formatter dropped every structured
    field attached by ``core.observability.log_event`` — so the useful observability
    payload never reached the terminal. Tracebacks are left to RichHandler.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        fields = getattr(record, "event_fields", None)
        if fields:
            # `event` is already the message; don't repeat it.
            extra = {key: value for key, value in fields.items() if key != "event"}
            if extra:
                message = f"{message} {json.dumps(extra, default=str, sort_keys=True)}"
        return f"{record.name}: {message}"


def _configure(level: int) -> None:
    global _CONFIGURED

    handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        tracebacks_show_locals=False,  # was True — dumped every local var on errors
        show_path=False,  # keep lines compact; logger name is in the message
        markup=False,  # structured JSON fields can contain '[' — don't parse markup
    )
    handler.setFormatter(EventFieldFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str, level: int | None = None) -> logging.Logger:
    """Return a logger, configuring the root handler once.

    Level resolution (first match wins): explicit ``level`` arg -> ``LOG_LEVEL`` env
    -> ``INFO``. Set ``LOG_LEVEL=DEBUG`` to surface the verbose per-node diagnostics
    (normalized queries, plans, SQL, row dumps) that are otherwise hidden.
    """
    if not _CONFIGURED:
        if level is None:
            env_level = os.getenv("LOG_LEVEL", "INFO").upper()
            level = getattr(logging, env_level, logging.INFO)
        _configure(level)
    return logging.getLogger(name)
