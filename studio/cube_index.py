"""The inverted index a cube is answered from — posting lists, not a row scan.

Both Studio cubes (:mod:`studio.filter_cube`, :mod:`studio.scope_cube`) hold the same thing:
the DISTINCT COMBINATIONS of the Setup filter columns. What changed here is how a selection
is resolved over them.

The original cubes stored their combinations as tuples of strings and answered a selection by
walking every one of them in Python. That is O(combinations) per keystroke — fine for a seed
book (~13k) and hopeless for a real one: ten filter columns over an 80M-row warehouse produce
millions of combinations, the cubes declined to build past 400k, and every filter change fell
back to ten ``SELECT DISTINCT … WHERE`` scans of the fact table.

So the combinations are stored the way a column store or a search engine stores them:

* **dictionary encoded** — each column's values are numbered, and the column becomes one
  ``int32`` array of codes. Comparisons are integer, and the whole cube is a handful of flat
  arrays that can be memory-mapped from disk rather than parsed;
* **inverted** — for each column, a posting list per value: the row ids carrying it. Built
  lazily, from one ``argsort`` of that column's codes.

A selection is then resolved the way an inverted index resolves a conjunction: start from the
SMALLEST posting list among the constrained columns, then narrow those candidate ids by the
remaining constraints. The cost is proportional to the rows the narrowest constraint admits —
not to the size of the cube, and not to the 80M rows behind it. Picking a carrier touches only
that carrier's rows, so the answer lands in milliseconds however large the warehouse grows.

Pure and IO-free on purpose: this module knows nothing about SQL, files, or what a cube is
FOR. Building and caching is :mod:`studio.cube_store`; the cascade and the rollup are each
cube's own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from studio import cube_core

# A constraint, resolved against the index: a column and the string keys it allows.
Constraint = Tuple[str, Tuple[str, ...]]

# Row ids and codes are int32 — a cube past 2**31 combinations is far past any sane cap.
_ID = np.int32
_CODE = np.int32

_NO_ROWS = np.empty(0, dtype=_ID)


@dataclass(frozen=True)
class Column:
    """One dictionary-encoded column of the cube.

    ``codes`` is row-aligned; ``keys`` and ``values`` are indexed BY code. ``keys`` are the
    string forms a selection is compared against, and ``values`` the original values (a year
    stays an ``int``, so a dropdown option still matches the stored selection). Codes are
    assigned in ``keys``-sorted order, which is what makes ``np.unique`` over a slice come
    back in the order the old ``sorted(seen)`` produced.
    """

    codes: np.ndarray
    keys: Tuple[str, ...]
    values: Tuple[Any, ...]

    def counts(self) -> np.ndarray:
        """How many rows carry each code — the posting sizes, without building the postings."""
        return np.bincount(self.codes, minlength=len(self.keys))


class CubeIndex:
    """The cube's columns, plus the three questions a cube is ever asked of them.

    :meth:`select` narrows to row ids, :meth:`distinct_values` reads a column off those ids,
    and :meth:`sums_by_code` adds a measure up over them. Posting lists are built on first
    use and kept, so the columns a user actually filters on pay for their index once.
    """

    def __init__(self, columns: Sequence[str], encoded: Mapping[str, Column]) -> None:
        self.columns: Tuple[str, ...] = tuple(columns)
        self._columns: Dict[str, Column] = dict(encoded)
        self._counts: Dict[str, np.ndarray] = {}
        self._lookups: Dict[str, Mapping[str, int]] = {}
        self._postings: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

    # ── shape ────────────────────────────────────────────────────────────────

    @property
    def n_rows(self) -> int:
        first = next(iter(self._columns.values()), None)
        return 0 if first is None else int(first.codes.size)

    def has(self, column: str) -> bool:
        return column in self._columns

    def column(self, column: str) -> Column:
        return self._columns[column]

    def values_of(self, column: str) -> Tuple[Any, ...]:
        """Every value of ``column``, in the cube's order — the unfiltered dropdown list."""
        col = self._columns.get(column)
        return () if col is None else col.values

    # ── resolving a selection ────────────────────────────────────────────────

    def constraints(self, selected: Mapping[str, Any],
                    *, skip: Sequence[str] = ()) -> List[Constraint]:
        """``selected`` as this index's constraints; columns it does not hold are dropped."""
        indexed = cube_core.constraints_for(self.columns, selected, skip=skip)
        return [(self.columns[i], keys) for i, keys in indexed
                if self.columns[i] in self._columns]

    def select(self, constraints: Sequence[Constraint]) -> Optional[np.ndarray]:
        """The row ids satisfying every constraint — ``None`` meaning "every row".

        ``None`` rather than ``arange(n)`` so the unconstrained case, which is most of a
        cascade, costs nothing at all.
        """
        if not constraints:
            return None
        plans = self._plan(constraints)
        if plans is None:
            return _NO_ROWS
        _, seed_column, seed_codes = plans[0]
        ids = self._postings_for(seed_column, seed_codes)
        for _, column, codes in plans[1:]:
            if ids.size == 0:
                break
            ids = ids[np.isin(self._columns[column].codes[ids], codes)]
        return ids

    def _plan(self, constraints: Sequence[Constraint]):
        """``[(rows admitted, column, codes)]`` most selective first, or None if impossible.

        The order is the whole optimisation: the first constraint decides how many candidate
        ids the rest of the work touches, and the row counts that decide it are precomputed
        (one ``bincount`` per column), so planning itself reads no rows.
        """
        plans = []
        for column, keys in constraints:
            codes = self.codes_for(column, keys)
            if codes.size == 0:
                return None            # a value no combination carries: nothing can match
            counts = self._counts_for(column)
            plans.append((int(counts[codes].sum()), column, codes))
        plans.sort(key=lambda plan: plan[0])
        return plans

    def codes_for(self, column: str, keys: Sequence[str]) -> np.ndarray:
        """``keys`` as codes of ``column``; keys the cube has never seen are dropped."""
        col = self._columns.get(column)
        if col is None:
            return np.empty(0, dtype=_CODE)
        lookup = self._key_lookup(column)
        return np.fromiter((lookup[k] for k in keys if k in lookup), dtype=_CODE)

    def _key_lookup(self, column: str) -> Mapping[str, int]:
        if column not in self._lookups:
            self._lookups[column] = {k: i for i, k in enumerate(self._columns[column].keys)}
        return self._lookups[column]

    def _counts_for(self, column: str) -> np.ndarray:
        if column not in self._counts:
            self._counts[column] = self._columns[column].counts()
        return self._counts[column]

    def _postings_for(self, column: str, codes: np.ndarray) -> np.ndarray:
        """The row ids carrying any of ``codes``, ascending."""
        order, offsets = self._inverted(column)
        if codes.size == 1:
            code = int(codes[0])
            return order[offsets[code]:offsets[code + 1]]
        parts = [order[offsets[int(c)]:offsets[int(c) + 1]] for c in codes]
        joined = np.concatenate(parts) if parts else _NO_ROWS
        joined.sort()
        return joined

    def _inverted(self, column: str) -> Tuple[np.ndarray, np.ndarray]:
        """``(row ids grouped by code, offset per code)`` — this column's posting lists.

        One stable ``argsort`` of the codes groups every value's rows together, and the
        running total of the code counts says where each group starts. Built once per column,
        and only for the columns a selection actually constrains.
        """
        if column not in self._postings:
            col = self._columns[column]
            order = np.argsort(col.codes, kind="stable").astype(_ID, copy=False)
            offsets = np.zeros(len(col.keys) + 1, dtype=np.int64)
            np.cumsum(self._counts_for(column), out=offsets[1:])
            self._postings[column] = (order, offsets)
        return self._postings[column]

    # ── reading the selected rows ────────────────────────────────────────────

    def distinct_codes(self, column: str, ids: Optional[np.ndarray]) -> np.ndarray:
        """``column``'s codes present in ``ids`` (all of them when ``ids`` is None)."""
        col = self._columns[column]
        if ids is None:
            return np.arange(len(col.keys), dtype=_CODE)
        if ids.size == 0:
            return np.empty(0, dtype=_CODE)
        return np.unique(col.codes[ids])

    def distinct_values(self, column: str, ids: Optional[np.ndarray]) -> List[Any]:
        """``column``'s surviving values, in the cube's (key-sorted) order."""
        col = self._columns.get(column)
        if col is None:
            return []
        if ids is None:
            return list(col.values)
        return [col.values[c] for c in self.distinct_codes(column, ids)]

    def sums_by_code(self, column: str, ids: Optional[np.ndarray],
                     weights: np.ndarray) -> List[Tuple[str, float]]:
        """``[(key, summed weight)]`` per value of ``column`` PRESENT in ``ids``.

        Values absent from the selected rows are left out rather than reported as zero — a
        rank counts the field that actually writes in the scope, and padding it with carriers
        that do not would change the "of n".
        """
        col = self._columns.get(column)
        if col is None:
            return []
        codes = col.codes if ids is None else col.codes[ids]
        if codes.size == 0:
            return []
        picked = weights if ids is None else weights[ids]
        totals = np.bincount(codes, weights=picked, minlength=len(col.keys))
        return [(col.keys[c], float(totals[c])) for c in np.unique(codes)]

    def sum_over(self, ids: Optional[np.ndarray], weights: np.ndarray) -> float:
        """``SUM(weights)`` over the selected rows."""
        if ids is None:
            return float(weights.sum())
        return 0.0 if ids.size == 0 else float(weights[ids].sum())


# ── building an index out of rows ────────────────────────────────────────────


class CubeEncoder:
    """Folds streamed rows into dictionary-encoded columns.

    Streamed, because the source is a ``GROUP BY`` over the whole warehouse: materialising
    millions of result rows as Python tuples costs gigabytes, so rows arrive in chunks and
    each chunk is encoded to ``int32`` and released. :meth:`add` returns False once
    ``max_rows`` is passed, which is how a caller declines a source too wide to cube.
    """

    def __init__(self, columns: Sequence[str], *, with_measure: bool = False,
                 max_rows: Optional[int] = None) -> None:
        self.columns = tuple(columns)
        self._with_measure = with_measure
        self._max_rows = max_rows
        self._tables: List[Dict[str, int]] = [{} for _ in self.columns]
        self._values: List[List[Any]] = [[] for _ in self.columns]
        self._parts: List[List[np.ndarray]] = [[] for _ in self.columns]
        self._measures: List[np.ndarray] = []
        self.n_rows = 0

    def add(self, rows: Sequence[Sequence[Any]]) -> bool:
        """Encode one chunk. False means the cap is passed and the cube is not worth it."""
        if not rows:
            return True
        buckets: List[List[int]] = [[] for _ in self.columns]
        for row in rows:
            for i, value in enumerate(row[:len(self.columns)]):
                table, values = self._tables[i], self._values[i]
                key = cube_core.key_of(value)
                code = table.get(key)
                if code is None:
                    code = table[key] = len(values)
                    values.append(value)
                buckets[i].append(code)
        for i, bucket in enumerate(buckets):
            self._parts[i].append(np.fromiter(bucket, dtype=_CODE, count=len(bucket)))
        if self._with_measure:
            self._measures.append(np.fromiter(
                (float(row[-1] or 0.0) for row in rows), dtype=np.float64, count=len(rows)))
        self.n_rows += len(rows)
        return self._max_rows is None or self.n_rows <= self._max_rows

    def finish(self) -> Tuple[CubeIndex, Optional[np.ndarray]]:
        """The index, and the measure column when one was encoded.

        Codes are renumbered into key-sorted order here — assigning them first-seen while
        streaming and permuting once at the end costs one pass, and it is what lets every
        later read come back sorted for free.
        """
        encoded: Dict[str, Column] = {}
        for i, column in enumerate(self.columns):
            codes = (np.concatenate(self._parts[i]) if self._parts[i]
                     else np.empty(0, dtype=_CODE))
            keys = list(self._tables[i])
            order = sorted(range(len(keys)), key=lambda c: keys[c])
            remap = np.empty(len(keys), dtype=_CODE)
            for rank, code in enumerate(order):
                remap[code] = rank
            encoded[column] = Column(
                codes=remap[codes] if len(keys) else codes,
                keys=tuple(keys[c] for c in order),
                values=tuple(self._values[i][c] for c in order),
            )
        measures = (np.concatenate(self._measures) if self._measures
                    else (np.empty(0, dtype=np.float64) if self._with_measure else None))
        return CubeIndex(self.columns, encoded), measures


def encode_rows(columns: Sequence[str], rows: Iterable[Sequence[Any]], *,
                with_measure: bool = False) -> Tuple[CubeIndex, Optional[np.ndarray]]:
    """Encode an in-memory sequence of rows — the small-source path (a dataset frame)."""
    encoder = CubeEncoder(columns, with_measure=with_measure)
    encoder.add(list(rows))
    return encoder.finish()
