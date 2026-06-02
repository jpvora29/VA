from __future__ import annotations
import logging
from rich.logging import RichHandler
from rich.console import Console
from rich.theme import Theme


# --- Custom theme ---
CUSTOM_THEME = Theme({
    "info":     "bold cyan",
    "warning":  "bold yellow",
    "error":    "bold red",
    "critical": "bold white on red",
    "success":  "bold green",
    "pipeline": "bold magenta",   # for pipeline stage logs
    "config":   "bold blue",      # for config load logs
})

console = Console(theme=CUSTOM_THEME)


def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                tracebacks_show_locals=True,   # shows local vars on exception
                show_path=True,                # shows file:line
                markup=True,                   # enables [bold red] in log messages
            )
        ],
        force=True,   # overrides any previously set handlers
    )
    return logging.getLogger(name)