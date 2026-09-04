"""Within one build, the same question is asked once.

A deck asks the warehouse the same things over and over. The overall block, the
trading summary, the ranking page and each product page all want the subject's
totals for the same scope, and each used to compute them for itself. Measured on
one single-country build:

    305 primitive calls, 88 distinct  ->  217 exact repeats, 35.1s of 57.5s (61%)

``product_breakdown_rows`` alone ran 63 times for 9 distinct arguments.

This is a **build-scoped** memo, not an ``lru_cache``. The distinction is the
whole design:

* a process-lifetime cache would serve a second build stale numbers after a data
  refresh, and would grow without bound across selections;
* this one lives inside ``with build_memo():`` and is discarded when the build
  ends, so a memo can never outlive the run whose data it describes.

**Returned values are copied out.** A primitive returns a list of row dicts, and a
caller that sorted or annotated a cached list in place would corrupt every later
reader of it — a bug that would surface as one page's numbers appearing on
another. Copying costs microseconds against a call that costs a third of a
second, so correctness wins with room to spare.

**Threads.** The cache lives in a :class:`~contextvars.ContextVar`, so a worker
thread that does not inherit the context simply misses the cache and computes —
slower, never wrong.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class Memo:
    """One build's answers, and how often they were reused."""

    values: Dict[Tuple, Any] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    @property
    def saved_calls(self) -> int:
        return self.hits


_ACTIVE: ContextVar[Optional[Memo]] = ContextVar("studio_build_memo", default=None)


def _key_part(value: Any) -> Any:
    """A hashable, order-stable stand-in for one argument.

    Mappings and sequences become sorted tuples so ``{"a": 1, "b": 2}`` and
    ``{"b": 2, "a": 1}`` are one key. An engine (or a pandas FrameSource) is keyed
    by IDENTITY: two engines are interchangeable only if they are the same object,
    and that is exactly the guarantee needed to never mix two data sources.
    """
    if isinstance(value, dict):
        return ("dict", tuple(sorted((str(k), _key_part(v)) for k, v in value.items())))
    if isinstance(value, (list, tuple)):
        return ("seq", tuple(_key_part(v) for v in value))
    if isinstance(value, (set, frozenset)):
        return ("set", tuple(sorted(str(v) for v in value)))
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return ("id", id(value))


def _key(fn_name: str, args: Tuple, kwargs: Dict[str, Any]) -> Tuple:
    return (
        fn_name,
        tuple(_key_part(a) for a in args),
        tuple(sorted((k, _key_part(v)) for k, v in kwargs.items())),
    )


def memoized(fn: F) -> F:
    """Answer from this build's memo when the same call was already made.

    Outside a ``build_memo()`` the wrapper is a straight pass-through, so a
    primitive called from the chatbot, a test, or the Overall page behaves exactly
    as it did before.
    """

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        memo = _ACTIVE.get()
        if memo is None:
            return fn(*args, **kwargs)
        key = _key(fn.__qualname__, args, kwargs)
        if key in memo.values:
            memo.hits += 1
            return copy.deepcopy(memo.values[key])
        memo.misses += 1
        result = fn(*args, **kwargs)
        memo.values[key] = result
        return copy.deepcopy(result)

    return wrapper  # type: ignore[return-value]


@contextmanager
def build_memo(label: str = "build"):
    """Memoise the analytics primitives for the duration of one build.

    Re-entrant: a nested ``build_memo`` keeps the outer one, so a caller that
    opens it around the whole build and an inner step that opens it around its own
    work share a single cache rather than fighting over two.
    """
    existing = _ACTIVE.get()
    if existing is not None:
        yield existing
        return

    memo = Memo()
    token = _ACTIVE.set(memo)
    try:
        yield memo
    finally:
        _ACTIVE.reset(token)
        total = memo.hits + memo.misses
        if total:
            logger.info(
                "studio memo[%s]: %d call(s), %d computed, %d served from memo (%.0f%%)",
                label, total, memo.misses, memo.hits, 100 * memo.hits / total,
            )


def active_memo() -> Optional[Memo]:
    """The build memo in force, or None outside a build (for tests and logging)."""
    return _ACTIVE.get()
