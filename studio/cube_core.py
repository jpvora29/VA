"""The shared mechanics of a cached in-memory cube.

Studio keeps two cubes over the same filter grain, because the Setup page asks two
different questions on every change:

* :mod:`studio.filter_cube` — "which values are still selectable?" (the cascade);
* :mod:`studio.scope_cube` — "what do the selected rows add up to?" (the preview).

Both are the DISTINCT COMBINATIONS of the filter columns, both are far smaller than the fact
table, both are built once per data source and cached to disk, and both answer a selection by
scanning their rows in memory. This module owns what they genuinely share — how a selection
becomes constraints, how a row is matched, and how a cache entry is keyed to the source it
came from — so neither cube has to spell it out twice.

Nothing here touches a database or knows what a cube is FOR. That is each cube's own job.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Sequence, Tuple

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


def matching(rows: Sequence[Tuple[str, ...]],
             constraints: Sequence[Constraint]) -> Iterable[int]:
    """The indices of the rows satisfying every constraint (all of them when there are none)."""
    if not constraints:
        return range(len(rows))
    return (i for i, row in enumerate(rows)
            if all(row[c] in allowed for c, allowed in constraints))


# ── keying a cache entry to the source it was built from ─────────────────────


def source_fingerprint(engine, table: str) -> Any:
    """A key that changes when the underlying database file does.

    SQLite is a file, so size+mtime is a cheap, exact "has the data changed?" signal. A
    non-file engine falls back to its URL, which simply means the cube lives for the process.
    """
    url = str(getattr(engine, "url", engine))
    path = getattr(getattr(engine, "url", None), "database", None)
    if path and Path(path).exists():
        stat = Path(path).stat()
        return (url, table, stat.st_size, int(stat.st_mtime))
    return (url, table)


def cache_path(directory: Path, prefix: str, *parts: Any) -> Path:
    """``<directory>/<prefix>_<digest>.json`` for the given cache-key parts."""
    sig = hashlib.blake2s(repr(parts).encode("utf-8"), digest_size=8).hexdigest()
    return directory / f"{prefix}_{sig}.json"
