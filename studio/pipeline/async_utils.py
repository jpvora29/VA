"""Small async helpers — ordered gathering, bounded concurrency, a sync bridge.

The plan's async rules: parallelize only independent work, never let parallelism
change result order, keep a synchronous wrapper for Dash callbacks.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Coroutine, List, Sequence, TypeVar

T = TypeVar("T")


async def gather_ordered(aws: Sequence[Awaitable[T]]) -> List[T]:
    """Run awaitables concurrently; results come back in INPUT order, always."""
    if not aws:
        return []
    return list(await asyncio.gather(*aws))


async def bounded_gather(aws: Sequence[Awaitable[T]], *, limit: int = 4) -> List[T]:
    """`gather_ordered` under a semaphore — at most ``limit`` run at once."""
    if not aws:
        return []
    sem = asyncio.Semaphore(max(1, limit))

    async def _run(aw: Awaitable[T]) -> T:
        async with sem:
            return await aw

    return list(await asyncio.gather(*(_run(a) for a in aws)))


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` from synchronous code (Dash callbacks, CLI, tests).

    Uses ``asyncio.run`` when no loop is running; otherwise hops to a fresh
    thread so we never re-enter a live event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
