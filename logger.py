from __future__ import annotations

import logging
import os
import sys

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


def _use_utf8() -> None:
    """Ask the console for UTF-8 so the glyph set is available.

    A Windows terminal reports cp1252 by default, which cannot encode the level
    markers, the box-drawing a table draws with, or the banner's block letters —
    all of which then print as "?". Reconfiguring the stream fixes it on every
    modern terminal; a console that refuses keeps its encoding, and
    `log_console.supports_glyphs` falls the renderer back to ASCII.

    `LOG_UTF8=off` skips it, for a genuinely legacy console where writing UTF-8
    would be worse than the ASCII fallback.
    """
    if os.getenv("LOG_UTF8", "on").strip().lower() == "off":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001 - not every stream is reconfigurable
            pass


def _configure(level: int) -> None:
    global _CONFIGURED

    _use_utf8()

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


def print_startup_banner(tagline: str = "") -> None:
    """The wordmark plus the models this process will use, once, at startup.

    Lives here because this module owns the console. Reads the tier table lazily
    so importing the logger never touches the LLM configuration layer.
    """
    import log_banner

    get_logger(__name__)  # ensure the console is configured (and UTF-8 asked for)
    try:
        from core.llm.clients import describe_tiers

        tiers = describe_tiers()
    except Exception:  # noqa: BLE001 - a banner must never stop a boot
        tiers = None
    ink = log_banner.BLOCK if log_console.supports_glyphs(console) else log_banner.ASCII_INK
    log_banner.print_banner(console, tiers=tiers, ink=ink, tagline=tagline)
