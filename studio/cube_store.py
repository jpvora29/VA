"""Where a cube comes from and where it lives — one scan per database, then a mmap.

The cube itself is :mod:`studio.cube_index`; this module is the boundary around it: the one
``GROUP BY`` that builds it, and the on-disk artifact that means only the FIRST launch for a
given database ever pays for that.

Three things here matter at warehouse scale.

**The scan is streamed.** A ``GROUP BY`` over the ten filter columns of an 80M-row book
returns millions of rows, and ``fetchall()`` on that is gigabytes of Python tuples before a
single one is encoded. Rows arrive in chunks and each chunk is encoded to ``int32`` and
released, so the build's memory is the cube's, not the result set's.

**The artifact is arrays, not JSON.** The cubes used to persist as a JSON list of row tuples;
at a few million rows that file is hundreds of megabytes and parsing it costs more than the
query it saves. A cube is now a directory of ``.npy`` files loaded with ``mmap_mode="r"`` — no
parse at all, and the pages the cascade touches are the only ones read.

**One artifact serves both cubes.** The filter cascade and the scope preview are the same
distinct combinations at the same grain; the rollup just carries a measure alongside. Keyed on
(database fingerprint, columns, measure), so whichever cube is asked for first builds it and
the other reads it off the disk tier — one scan of the fact table, not two.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import text

from logger import get_logger
from studio import cube_core
from studio.cube_index import Column, CubeEncoder, CubeIndex

logger = get_logger(__name__)

# Rows pulled from the database per chunk. Large enough that the per-chunk overhead is
# noise, small enough that a chunk is never itself a memory problem.
_CHUNK = 250_000

# Above this many distinct combinations a cube stops being a shortcut: it is held in memory
# (or mapped from disk) and its posting lists are built in it, so the cap is about FOOTPRINT,
# not about scan cost — resolving a selection no longer depends on how many combinations
# there are. Ten int32 columns at 8M rows is ~320 MB mapped, which a workstation carries.
# ``STUDIO_CUBE_MAX_ROWS`` tunes it for a warehouse with a wider dimensional grain.
_DEFAULT_MAX_ROWS = 8_000_000


def max_rows() -> int:
    """The combination cap, from ``STUDIO_CUBE_MAX_ROWS`` (default 8M)."""
    raw = os.getenv("STUDIO_CUBE_MAX_ROWS", "").strip()
    try:
        return int(raw) if raw else _DEFAULT_MAX_ROWS
    except ValueError:
        logger.warning("cube_store: STUDIO_CUBE_MAX_ROWS=%r is not a number — using %d",
                       raw, _DEFAULT_MAX_ROWS)
        return _DEFAULT_MAX_ROWS


@dataclass(frozen=True)
class CubeData:
    """A built cube: the index over its combinations, and the measure rolled up to them.

    ``measures`` is None for a cube built without one — the filter cascade never needs it.
    """

    columns: Tuple[str, ...]
    index: CubeIndex
    measures: Optional[np.ndarray] = None

    @property
    def n_rows(self) -> int:
        return self.index.n_rows


# ── building ─────────────────────────────────────────────────────────────────


def _select_sql(table: str, columns: Sequence[str], measure: Optional[str]) -> str:
    """The one query a cube is built from.

    ``table``, ``columns`` and ``measure`` are verified schema identifiers supplied by the
    flow registry, never user input.
    """
    quoted = ", ".join(f'"{c}"' for c in columns)
    if measure:
        return f'SELECT {quoted}, SUM("{measure}") FROM "{table}" GROUP BY {quoted}'
    return f"SELECT DISTINCT {quoted} FROM \"{table}\""


def build_sql(engine, table: str, columns: Sequence[str], *, measure: Optional[str] = None,
              cap: Optional[int] = None) -> Optional[CubeData]:
    """Build a cube from one streamed pass over ``table``, or None if it declines.

    Declines for either reason a cube can be the wrong tool: the source is unreadable (a
    missing table, a permission), or its dimensional grain is wider than ``cap``. Both mean
    the caller falls back to its original SQL — same answers, slower.
    """
    cap = max_rows() if cap is None else cap
    encoder = CubeEncoder(columns, with_measure=bool(measure), max_rows=cap)
    started = time.time()
    try:
        with engine.connect() as conn:
            streamed = conn.execution_options(stream_results=True, yield_per=_CHUNK)
            result = streamed.execute(text(_select_sql(table, columns, measure)))
            for chunk in result.partitions(_CHUNK):
                if not encoder.add(chunk):
                    result.close()
                    logger.warning(
                        "cube_store: %s has >%d filter combinations — falling back to SQL "
                        "(raise STUDIO_CUBE_MAX_ROWS to cube it anyway)", table, cap)
                    return None
    except Exception as exc:  # noqa: BLE001 — a cube is an optimisation, never a requirement
        logger.warning("cube_store: %s cube unavailable, falling back to SQL: %s", table, exc)
        return None
    index, measures = encoder.finish()
    logger.info("cube_store: %s cube built — %d combination(s) over %d column(s) in %.1fs",
                table, index.n_rows, len(index.columns), time.time() - started)
    return CubeData(columns=tuple(columns), index=index, measures=measures)


def build_frame(frame, columns: Sequence[str], *, measure: Optional[str] = None,
                cap: Optional[int] = None) -> Optional[CubeData]:
    """The same cube for an uploaded dataset's in-memory frame."""
    cap = max_rows() if cap is None else cap
    present = [c for c in columns if c in getattr(frame, "columns", ())]
    if not present:
        return None
    if measure:
        if measure not in getattr(frame, "columns", ()):
            return None
        rolled = frame.groupby(present, dropna=False)[measure].sum().reset_index()
    else:
        rolled = frame[present].drop_duplicates()
    if len(rolled) > cap:
        logger.warning("cube_store: dataset has >%d filter combinations — using the frame scan",
                       cap)
        return None
    encoder = CubeEncoder(present, with_measure=bool(measure), max_rows=cap)
    encoder.add(list(rolled.itertuples(index=False, name=None)))
    index, measures = encoder.finish()
    return CubeData(columns=tuple(present), index=index, measures=measures)


def from_rows(columns: Sequence[str], rows, *, measure: bool = False) -> CubeData:
    """A cube from rows already in hand — the small-source and test path."""
    encoder = CubeEncoder(columns, with_measure=measure)
    encoder.add(list(rows))
    index, measures = encoder.finish()
    return CubeData(columns=tuple(columns), index=index, measures=measures)


# ── the disk tier ────────────────────────────────────────────────────────────
#
# A directory per cube: one .npy per column plus one for the measure, and a meta.json
# holding the value dictionaries. meta.json is written LAST, so its presence is what marks
# an artifact complete — a build interrupted half way is simply not found.

_META = "meta.json"
_FORMAT = 2                    # bumped when the layout changes, so old artifacts are ignored


def artifact_dir(disk_dir: Path, fingerprint: Any, columns: Sequence[str],
                 measure: Optional[str]) -> Path:
    """Where the cube for this (database, columns, measure) lives."""
    path = cube_core.cache_path(disk_dir, "cube", _FORMAT, fingerprint,
                               tuple(columns), measure)
    return path.with_suffix("")


def _plain(value: Any) -> Any:
    """A numpy scalar as plain Python, so the value dictionaries are JSON-writable."""
    return value.item() if hasattr(value, "item") else value


def read_disk(directory: Path, columns: Sequence[str],
              measure: Optional[str]) -> Optional[CubeData]:
    """The cube persisted in ``directory``, mapped not parsed, or None if it is not there."""
    try:
        with open(directory / _META, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None
    if meta.get("format") != _FORMAT or tuple(meta.get("columns", ())) != tuple(columns):
        return None
    if bool(meta.get("measure")) != bool(measure):
        return None
    try:
        encoded: Dict[str, Column] = {}
        for i, column in enumerate(columns):
            codes = np.load(directory / f"codes_{i}.npy", mmap_mode="r")
            vocab = meta["vocab"][i]
            encoded[column] = Column(codes=codes,
                                     keys=tuple(vocab["keys"]),
                                     values=tuple(vocab["values"]))
        measures = (np.load(directory / "measures.npy", mmap_mode="r") if measure else None)
    except (OSError, ValueError, KeyError, IndexError) as exc:  # noqa: BLE001
        logger.debug("cube_store: artifact at %s unreadable (%s) — rebuilding", directory, exc)
        return None
    return CubeData(columns=tuple(columns), index=CubeIndex(columns, encoded),
                    measures=measures)


def write_disk(directory: Path, cube: CubeData, measure: Optional[str]) -> None:
    """Persist ``cube`` so the next launch maps it instead of scanning for it."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        vocab: List[Dict[str, Any]] = []
        for i, column in enumerate(cube.columns):
            col = cube.index.column(column)
            np.save(directory / f"codes_{i}.npy", np.asarray(col.codes))
            vocab.append({"keys": list(col.keys),
                          "values": [_plain(v) for v in col.values]})
        if measure and cube.measures is not None:
            np.save(directory / "measures.npy", np.asarray(cube.measures))
        meta = {"format": _FORMAT, "columns": list(cube.columns),
                "measure": measure, "rows": cube.n_rows, "vocab": vocab}
        tmp = directory / (_META + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        tmp.replace(directory / _META)                 # last, and atomic: marks it complete
    except (OSError, TypeError, ValueError) as exc:    # noqa: BLE001 — cache is best-effort
        logger.debug("cube_store: disk write failed: %s", exc)


# ── the cached entry point both cubes use ────────────────────────────────────


def load_or_build_sql(engine, table: str, columns: Sequence[str], *,
                      measure: Optional[str] = None, disk_dir: Path,
                      cap: Optional[int] = None) -> Optional[CubeData]:
    """The cube for a database table — the disk tier, else one streamed scan.

    No memory tier here on purpose: each cube keeps its own (it caches the wrapper, not the
    arrays), and the arrays themselves are mapped, so a second reader is a page-table entry
    rather than a copy.
    """
    fingerprint = cube_core.source_fingerprint(engine, table)
    directory = artifact_dir(disk_dir, fingerprint, columns, measure)
    cube = read_disk(directory, columns, measure)
    if cube is not None:
        logger.info("cube_store: %s cube mapped from disk (%d combinations)",
                    table, cube.n_rows)
        return cube
    cube = build_sql(engine, table, columns, measure=measure, cap=cap)
    if cube is not None:
        write_disk(directory, cube, measure)
    return cube
