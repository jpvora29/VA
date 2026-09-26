"""Start independent model calls early; collect them where they are needed.

The graph is a chain because most steps depend on the one before. A few do not:
the ambiguity check only needs what the context filler resolved, yet it waited
behind the intent classifier. `start` launches such a call in a worker thread as
soon as its inputs exist, keyed by the turn's message id; the node that needs
it calls `take` and waits only for whatever time is left.

The worker runs inside a COPY of the caller's context, so the turn's callbacks
(the token meter, the Stop handler) and its trace fields travel with it — a
speculative call is metered and cancellable like any other.

Pure plumbing, no model imports. A speculation nobody collects is dropped after
`TTL_SECONDS`.
"""
from __future__ import annotations

import contextvars
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional, Tuple

TTL_SECONDS = 300

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="speculate")
_PENDING: Dict[str, Tuple[float, Future]] = {}
_LOCK = threading.Lock()


def _prune(now: float) -> None:
    for key in [k for k, (born, _) in _PENDING.items() if now - born > TTL_SECONDS]:
        _PENDING.pop(key, None)


def start(key: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Optional[Future]:
    """Run `fn(*args, **kwargs)` now, in the caller's context. Idempotent per key."""
    if not key:
        return None
    context = contextvars.copy_context()
    with _LOCK:
        now = time.monotonic()
        _prune(now)
        if key in _PENDING:
            return _PENDING[key][1]
        future = _POOL.submit(context.run, fn, *args, **kwargs)
        _PENDING[key] = (now, future)
        return future


def take(key: str) -> Optional[Future]:
    """The speculation started under `key`, removed from the registry, or None."""
    if not key:
        return None
    with _LOCK:
        entry = _PENDING.pop(key, None)
    return entry[1] if entry else None


def pending_keys() -> list:
    """For tests and diagnostics."""
    with _LOCK:
        return list(_PENDING)
