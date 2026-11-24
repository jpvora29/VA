"""When a usage row is written: off the request path, one write at a time, never fatal.

Settings (read on every call, so a test or an operator can flip them live):

    USAGE_METRICS       "off" / "0" / "false" disables recording (default: on)
    USAGE_METRICS_DIR   the folder the per-user workbooks go in
                        (default: ``usage_metrics/`` in the project folder)

The default folder is in the project on purpose: the project is the shared OneDrive
folder, so whoever owns it sees every user's workbook. Each workbook has a single
writer — its own user — which is why this is safe where a shared SQLite file is not.
"""

from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from core.usage_metrics.events import UsageActor, UsageEvent, make_actor
from core.usage_metrics.workbook import append_rows, workbook_path
from logger import get_logger

log = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OFF_VALUES = frozenset({"0", "off", "false", "no"})

# One worker: writes to a workbook are serialised without a lock, and a slow save
# never holds up a Dash callback.
_WRITER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="usage-metrics")


def usage_enabled() -> bool:
    return os.environ.get("USAGE_METRICS", "on").strip().lower() not in _OFF_VALUES


def usage_dir() -> Path:
    configured = os.environ.get("USAGE_METRICS_DIR", "").strip()
    return Path(configured) if configured else _PROJECT_ROOT / "usage_metrics"


def record_usage(actor: UsageActor | None, event: UsageEvent) -> Future | None:
    """Queue ``event`` for ``actor``'s workbook; ``None`` when recording is off.

    Never raises: usage logging must not cost the user the thing they were doing.
    """
    if actor is None or not usage_enabled():
        return None
    try:
        path = workbook_path(usage_dir(), actor.file_key)
        return _WRITER.submit(write_event, path, actor, event)
    except Exception:  # noqa: BLE001 — e.g. the executor is shut down at exit
        log.exception("usage metrics: could not queue a %s event", event.tab)
        return None


def write_event(path: Path, actor: UsageActor, event: UsageEvent) -> None:
    """Append one row; failures are logged, not raised (runs on the writer thread)."""
    try:
        append_rows(path, [event.as_row(actor)])
    except PermissionError:
        log.warning(
            "usage metrics: %s is locked (open in Excel?); row kept pending", path
        )
    except Exception:  # noqa: BLE001
        log.exception("usage metrics: could not write %s", path)


def actor_from_user_id(user_id: int | str | None) -> UsageActor | None:
    """The actor for a stored user id — for code with no browser store to read.

    A chat turn finishes on a worker thread, where the ``user-store`` is not at hand
    but the user id is.
    """
    if user_id is None:
        return None
    try:
        from core.store.users import get_user

        user = get_user(user_id) or {}
    except Exception:  # noqa: BLE001 — still record the row, under the bare id
        log.exception("usage metrics: could not look up user %s", user_id)
        user = {}
    return make_actor(user_id, user.get("username"))
