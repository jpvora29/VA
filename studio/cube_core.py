"""The shared mechanics of a cached in-memory cube.

Studio keeps two cubes over the same filter grain, because the Setup page asks two
different questions on every change:

* :mod:`studio.filter_cube` — "which values are still selectable?" (the cascade);
* :mod:`studio.scope_cube` — "what do the selected rows add up to?" (the preview).

Both are the DISTINCT COMBINATIONS of the filter columns, both are far smaller than the fact
table, and both are built once per data source and cached to disk. This module owns what they
genuinely share — how a selection becomes constraints, and how a cache entry is keyed to the
source it came from — so neither cube has to spell it out twice. How those constraints are
then RESOLVED is :mod:`studio.cube_index`; where a built cube comes from and lives is
:mod:`studio.cube_store`.

Nothing here touches a database or knows what a cube is FOR. That is each cube's own job.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, List, Mapping, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

# Values that mean "no constraint" on a Setup control.
BLANK = (None, "", "all", "All")

# A constraint is (column index, allowed string values).
Constraint = Tuple[int, Tuple[str, ...]]


def as_values(value: Any) -> Tuple[str, ...]:
    """A selection as a tuple of comparable strings (``()`` when it constrains nothing).

    Everything is compared as text so a year that is an ``int`` in the database and a
    ``str`` in the form still match; each cube keeps its own map back to the original value
    where the original type matters (a dropdown's option value, for one).
    """
    if value in BLANK:
        return ()
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    return tuple(str(v) for v in values if v not in BLANK)


def key_of(value: Any) -> str:
    """A single value in the string form the cube's rows are stored in."""
    return "" if value is None else str(value)


def constraints_for(columns: Sequence[str], selected: Mapping[str, Any],
                    *, skip: Sequence[str] = ()) -> List[Constraint]:
    """``selected`` as index-based constraints over ``columns``; unknown columns dropped."""
    index = {column: i for i, column in enumerate(columns)}
    out: List[Constraint] = []
    for column, value in (selected or {}).items():
        if column in skip:
            continue
        i = index.get(column)
        values = as_values(value)
        if i is not None and values:
            out.append((i, values))
    return out


def unknown_columns(columns: Sequence[str], selected: Mapping[str, Any]) -> List[str]:
    """The constraining columns ``columns`` cannot answer — the caller must fall back.

    A cube spans the filter vocabulary only. A selection on anything else (a client name, a
    billing date) is not a column it can filter on, and answering anyway would silently
    report a WIDER scope than the user asked for.
    """
    known = set(columns)
    return [c for c, v in (selected or {}).items() if c not in known and as_values(v)]


# ── keying a cache entry to the source it was built from ─────────────────────


def source_fingerprint(engine, table: str) -> Any:
    """A key that changes when the underlying database file does.

    SQLite is a file, so size+mtime is a cheap, exact "has the data changed?" signal. A
    non-file engine falls back to its URL, which simply means the cube lives for the process.

    ``STUDIO_CUBE_KEY`` replaces the file signature with a name you control. Use it when the
    database file is touched by something other than a data load — an index build, a VACUUM, a
    WAL checkpoint, another process writing to the same file — because each of those moves
    size or mtime and silently invalidates a cube that took minutes to build. With a pinned
    key the cube is rebuilt when you change the key, and not before.
    """
    url = str(getattr(engine, "url", engine))
    pinned = os.getenv("STUDIO_CUBE_KEY", "").strip()
    if pinned:
        return ("pinned", pinned, table)
    path = getattr(getattr(engine, "url", None), "database", None)
    if path and Path(path).exists():
        stat = Path(path).stat()
        fingerprint = (url, table, stat.st_size, int(stat.st_mtime))
        _warn_if_moved(url, table, fingerprint)
        return fingerprint
    return (url, table)


# What each (database, table) last fingerprinted as, so a file that keeps moving is REPORTED
# rather than quietly costing a rebuild every time it is asked for.
_seen: dict = {}


def _warn_if_moved(url: str, table: str, fingerprint: Any) -> None:
    previous = _seen.get((url, table))
    _seen[(url, table)] = fingerprint
    if previous is not None and previous != fingerprint:
        logger.warning(
            "cube: %s changed on disk (size/mtime %s → %s) — every cube built for it is "
            "invalidated and will be rebuilt. If the DATA did not change, set STUDIO_CUBE_KEY "
            "to pin the cube to a name you control.", table, previous[2:], fingerprint[2:])


def cache_path(directory: Path, prefix: str, *parts: Any) -> Path:
    """``<directory>/<prefix>_<digest>.json`` for the given cache-key parts."""
    sig = hashlib.blake2s(repr(parts).encode("utf-8"), digest_size=8).hexdigest()
    return directory / f"{prefix}_{sig}.json"
