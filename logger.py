from __future__ import annotations

import logging
import os

from rich.console import Console
from rich.theme import Theme

import log_console

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

    The one-line JSON rendering, kept because it is the right one for a log that
    is piped, grepped or diffed. The terminal gets `log_console` instead — see
    that module for why a bag of alphabetised JSON is unreadable on screen.
    """

    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "event_fields", None)
        if not fields:
            return f"{record.name}: {record.getMessage()}"
        return log_console.plain_line(record, fields)


def _configure(level: int) -> None:
    global _CONFIGURED

    # Events render as aligned columns with a rule per turn; `LOG_STYLE=plain`
    # falls back to the single-line JSON this handler also knows how to print.
    handler = log_console.EventConsoleHandler(
        console, plain=log_console.plain_style()
    )

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
