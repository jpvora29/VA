"""Run independent, network-bound work at the same time.

A deck has around a hundred commentary columns and each is a model call plus a verifier
that is another one. Run in a row that is the whole build: measured with a half-second
stand-in for the model, 93 columns took 46s serially and 6s eight at a time, and the real
tier is several seconds a call rather than half of one.

The work is I/O, not computation, so threads are the right tool and asyncio is not: the
model client is LangChain's blocking ``invoke``, and wrapping it would mean rewriting that
stack to get the concurrency a thread pool gives for free.
``studio.pipeline.async_utils`` stays the helper for work that is already awaitable.

Two rules, both about keeping a parallel build's output identical to a serial one:

* **Order is by position, never by completion.** :func:`gather_list` returns results in
  input order, so which task finishes first cannot change a deck.
* **Only give it independent work.** A task that reads what another task writes belongs
  in a sequence, not here.

One caller, on purpose. The analytics primitives look like the same kind of independent
work and are not: the engine is a local SQLite file and each primitive spends most of its
time in pandas afterwards, so batching them measured no faster than a plain loop. Reach
for this where the wait is a network round trip.

``STUDIO_MAX_WORKERS=1`` runs everything inline, which is how a confusing failure gets
debugged and how a test pins a build to one thread.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Sequence, TypeVar

T = TypeVar("T")

# Deliberately modest. These threads are waiting on a model endpoint, which has its own
# limit — a pool big enough to trip it turns a queue we can see into a rate-limit we
# cannot.
DEFAULT_WORKERS = 8


def max_workers() -> int:
    """How many tasks may be in flight at once (``STUDIO_MAX_WORKERS``, else 8)."""
    try:
        return max(1, int(os.environ.get("STUDIO_MAX_WORKERS", DEFAULT_WORKERS)))
    except ValueError:
        return DEFAULT_WORKERS


def gather_list(tasks: Sequence[Callable[[], T]], *, workers: int = 0) -> List[T]:
    """Run every task concurrently; results come back in INPUT order, always.

    Exceptions propagate, as they would from a serial loop — a caller that wants a
    failure tolerated wraps its own task, which is also where it knows what to fall
    back to.
    """
    if not tasks:
        return []
    limit = min(workers or max_workers(), len(tasks))
    if limit <= 1:
        return [task() for task in tasks]
    with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="studio") as pool:
        return list(pool.map(lambda task: task(), tasks))


