"""A run's WORKING BOOK — the slice of the warehouse one deck is computed from.

**Why a deck needs its own copy.** Generate asks the warehouse ~700 filtered aggregates
(measured on a three-country deck). Against the governed book each one scanned the whole fact
table — 89% of the build's wall clock at 1.9M rows, and the reason an 80M-row book took an
hour and a half while a 500k-row upload took minutes. But a deck only ever reads the markets
it was asked about. So Generate extracts those rows ONCE, into a small local SQLite file
with the analytics indexes built on it, and every query after that is an index search over
a few percent of the book. The SQL the primitives run is unchanged, so the answers are too.

**Why the reporting period lives here too.** The Setup form's R12M/TTM toggle and date range
change what "year Y" means (:mod:`studio.period`). Relabelling ``Year`` to the period year in
the working book — once, as it is built — is what lets every existing metric honour the
toggle without knowing it exists.

Two layers, each cached on disk and keyed on what it was built from:

    the governed book  --(markets, aggregated)-->  RAW slice     (one read of the warehouse)
    RAW slice          --(period relabel)------->  PERIOD book   (local, seconds)

so switching between calendar and R12M, or regenerating the same markets, never reads the
warehouse again. An uploaded dataset (a :class:`~core.analytics.frames.FrameSource`) is
already small and in memory; it gets the same relabel in pandas and no slice.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from core.analytics.frames import FrameSource, as_frame_source
from core.registry import get_flow_registry
from logger import get_logger
from studio import period as P

logger = get_logger(__name__)

_COUNTRY = "Country"
_REGION = "Region"
_YEAR = "Year"
_QUARTER = "Quarter"
_MONTH_NAME = "Month_Name"
_DATE = "Billing_Date"
# Row-level grain no page reads. Dropping it before aggregating is what lets the slice
# collapse to the dimensional grain (every other column is a dimension a page cuts by).
_ROW_GRAIN = ("CLIENT_NAME",)

# How many built books to keep on disk. Each is a few percent of the warehouse.
_KEEP = 8

# Part of every book's cache key. Bump it whenever the way a book is BUILT changes: the key
# otherwise only sees the data, so a fixed bug would keep being served from yesterday's file.
_BUILD_VERSION = 2


# ── what to build ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BookSpec:
    """Everything that decides a working book's contents — and so its cache key."""

    countries: Tuple[str, ...] = ()       # the markets to slice to; () = every market
    regions: Tuple[str, ...] = ()         # used only when no country is pinned
    choice: P.PeriodChoice = P.PeriodChoice()
    year_pin: Optional[int] = None
    with_survey: bool = False


@dataclass
class WorkingBook:
    """The engine a deck computes on, and the period it reports.

    ``window`` is ``None`` on the plain calendar basis. ``r12m`` answers the twelve months to
    the latest month whatever the basis — the Country page's TTM table always reports that —
    and is built on first use, from the same raw slice, so it costs no warehouse read.
    """

    engine: Any
    window: Optional[P.PeriodWindow] = None
    latest: Optional[Tuple[int, int]] = None
    _r12m: Optional[Callable[[], "WorkingBook"]] = field(default=None, repr=False)
    _r12m_book: Optional["WorkingBook"] = field(default=None, repr=False)

    def r12m(self) -> "WorkingBook":
        """The rolling-twelve-month book for this run (itself when already on R12M)."""
        if self.window is not None and self.window.kind == P.KIND_R12M:
            return self
        if self._r12m_book is None and self._r12m is not None:
            self._r12m_book = self._r12m()
        return self._r12m_book or self


def book_spec(selection: Dict[str, Any]) -> BookSpec:
    """The spec a Setup selection asks for."""
    filters = (selection or {}).get("filters") or {}
    return BookSpec(
        countries=_values(filters.get("country")),
        regions=_values(filters.get("region")),
        choice=P.period_choice(selection),
        year_pin=P.year_pin(filters.get("year")),
        with_survey=(selection or {}).get("data_basis") == "premium_survey",
    )


def _values(value: Any) -> Tuple[str, ...]:
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    return tuple(sorted({str(v) for v in values if v not in (None, "", "all", "All")}))


def raw_ready(source: Any, spec: BookSpec) -> bool:
    """Whether ``spec``'s slice of ``source`` is already on disk (an upload always is).

    What lets the Setup preview report R12M figures without making a filter change wait
    for a warehouse read: when the slice is there, the period book is seconds away.
    """
    if as_frame_source(source) is not None:
        return True
    try:
        key = _key("raw", _BUILD_VERSION, _fingerprint(source), spec.countries, spec.regions,
                   spec.with_survey)
    except Exception:  # noqa: BLE001 - an unreadable source is simply "not ready"
        return False
    return (book_dir() / f"raw_{key}.db").exists()


_prefetching: Dict[str, threading.Thread] = {}


def prefetch(source: Any, spec: BookSpec, *, wait: float = 0.0) -> bool:
    """Start slicing ``spec``'s markets in the background; ``True`` when it is ready now.

    ``wait`` seconds are spent waiting for the build — a small book is sliced in well under
    that, so the caller gets its answer this time; a large one keeps building and the
    caller answers without it.

    Setup calls this as soon as the author has picked markets, so the one warehouse read a
    deck needs is usually done before Generate is pressed. One build per key at a time; the
    build lock in :func:`_raw_slice` covers a Generate that arrives while it runs.
    """
    if raw_ready(source, spec):
        return True
    if not (spec.countries or spec.regions):
        return False
    key = repr((spec.countries, spec.regions, spec.with_survey))
    running = _prefetching.get(key)
    if running is not None and running.is_alive():
        running.join(wait)
        return raw_ready(source, spec)

    def build() -> None:
        try:
            _raw_slice(source, spec)
        except Exception as exc:  # noqa: BLE001 - a prefetch must never surface
            logger.warning("studio book: prefetch for %s failed: %s", key, exc)

    thread = threading.Thread(target=build, name="studio-book-prefetch", daemon=True)
    _prefetching[key] = thread
    thread.start()
    thread.join(wait)
    return raw_ready(source, spec)


def open_book(source: Any, spec: BookSpec) -> WorkingBook:
    """The working book for ``spec`` over ``source`` (an engine or a FrameSource)."""
    frames = as_frame_source(source)
    if frames is not None:
        return _frame_book(frames, spec)
    return _governed_book(source, spec)


# ── the governed book: slice once, relabel locally ───────────────────────────


def _governed_book(source: Any, spec: BookSpec) -> WorkingBook:
    """Slice ``source`` to the run's markets, then apply the period.

    A run that pins no market and needs no relabel reads the warehouse as it is — a copy of
    the whole book would cost more than the queries it saves.
    """
    sliced = bool(spec.countries or spec.regions)
    if not sliced and spec.choice.is_default:
        return WorkingBook(engine=source, _r12m=lambda: _governed_period(
            _raw_slice(source, spec), replace(spec, choice=P.PeriodChoice(P.BASIS_R12M))))
    raw = _raw_slice(source, spec)
    book = _governed_period(raw, spec)
    r12m_spec = replace(spec, choice=P.PeriodChoice(P.BASIS_R12M, date_to=spec.choice.date_to))
    book._r12m = lambda: _governed_period(raw, r12m_spec)
    return book


def book_dir() -> Path:
    """Where built books live — never under a synced folder unless the author says so.

    ``STUDIO_BOOK_DIR``, else ``<STUDIO_CACHE_DIR>/books``, else the system temp dir. Not
    ``studio/_cache``: that sits under OneDrive here, and a sync client re-uploading a
    multi-hundred-MB SQLite file on every build is exactly the slowness this module removes.
    """
    explicit = os.getenv("STUDIO_BOOK_DIR", "").strip()
    if explicit:
        return Path(explicit)
    cache = os.getenv("STUDIO_CACHE_DIR", "").strip()
    return Path(cache) / "books" if cache else Path(tempfile.gettempdir()) / "va_studio_books"


def _fingerprint(engine: Any) -> Tuple[Any, ...]:
    """What identifies the source's data — the same signal the filter cube keys on."""
    from studio.cube_core import source_fingerprint

    return tuple(source_fingerprint(engine, "GPR"))


def _key(*parts: Any) -> str:
    return hashlib.blake2s(repr(parts).encode("utf-8"), digest_size=10).hexdigest()


_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    """One build per key at a time: a second caller waits and reuses the first's file."""
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


@dataclass(frozen=True)
class _RawSlice:
    path: Path
    latest: Optional[Tuple[int, int]]
    has_iso_date: bool
    columns: Tuple[str, ...]


def _raw_slice(source: Any, spec: BookSpec) -> _RawSlice:
    """The run's markets, aggregated to the dimensional grain — built at most once."""
    key = _key("raw", _BUILD_VERSION, _fingerprint(source), spec.countries, spec.regions,
               spec.with_survey)
    path = book_dir() / f"raw_{key}.db"
    with _lock(str(path)):
        if not path.exists():
            _build_raw(source, spec, path)
        else:
            os.utime(path)                              # most-recently-used, for pruning
    return _describe(path)


def _source_path(engine: Any) -> str:
    path = getattr(getattr(engine, "url", None), "database", None)
    if not path or path == ":memory:":
        raise ValueError("the working book can only slice a file-backed SQLite warehouse")
    return str(Path(path).resolve())


def _read_only_uri(path: str) -> str:
    return Path(path).resolve().as_uri() + "?mode=ro"


def _connect(path: Path) -> sqlite3.Connection:
    """A build connection: URI-aware (for the read-only attach) and journal-free.

    No journal and no fsync because a half-written book is never used — it is written under
    a ``.building`` name and only renamed into place once complete.
    """
    conn = sqlite3.connect(Path(path).resolve().as_uri(), uri=True)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    return conn


def _table_columns(conn: sqlite3.Connection, schema: str, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _gpr_columns(conn: sqlite3.Connection) -> Tuple[List[str], str]:
    """``(dimension columns to keep, the measure)`` — registry columns the source really has."""
    spec = get_flow_registry().get("gpr")
    from core.analytics.sql import resolve_measure

    measure, _agg = resolve_measure(spec, "premium")
    have = _table_columns(conn, "src", spec.primary_table)
    declared = set(spec.columns)
    dims = [c for c in have if c in declared and c != measure and c not in _ROW_GRAIN]
    return dims, measure


def _market_where(spec: BookSpec, params: List[Any]) -> str:
    """``WHERE "Country" COLLATE NOCASE IN (…)`` — or by region when no country is pinned."""
    column, values = (_COUNTRY, spec.countries) if spec.countries else (_REGION, spec.regions)
    if not values:
        return ""
    params.extend(values)
    marks = ", ".join("?" for _ in values)
    return f' WHERE "{column}" COLLATE NOCASE IN ({marks})'


def _build_raw(source: Any, spec: BookSpec, path: Path) -> None:
    """One read of the warehouse: the run's markets, grouped to the dimensional grain."""
    started = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".building")
    partial.unlink(missing_ok=True)
    conn = _connect(partial)
    try:
        # Read-only: the warehouse is never written, and never locked for writing, by a build.
        conn.execute("ATTACH DATABASE ? AS src", (_read_only_uri(_source_path(source)),))
        dims, measure = _gpr_columns(conn)
        params: List[Any] = []
        cols = ", ".join(f'"{c}"' for c in dims)
        conn.execute(
            f'CREATE TABLE "GPR" AS SELECT {cols}, SUM("{measure}") AS "{measure}" '
            f'FROM src."GPR"{_market_where(spec, params)} GROUP BY {cols}', params)
        _copy_supporting(conn, spec)
        conn.commit()
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    partial.replace(path)
    rows = _count(path)
    logger.info("studio book: sliced %s to %s row(s) in %.1fs (%s)",
                ", ".join(spec.countries or spec.regions) or "the whole book", f"{rows:,}",
                time.time() - started, path.name)
    _prune(path.parent)


def _copy_supporting(conn: sqlite3.Connection, spec: BookSpec) -> None:
    """The small tables a deck also reads: the peer groups, and the survey book if used.

    The survey book is copied WHOLE: its pages match countries by their own spelling
    (``survey.scope.book_country``), which needs every country the book holds.
    """
    tables = ["Peers"] + (["Carriers"] if spec.with_survey else [])
    present = {r[0] for r in conn.execute(
        "SELECT name FROM src.sqlite_master WHERE type='table'")}
    for table in tables:
        if table in present:
            conn.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"')


def _count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute('SELECT COUNT(*) FROM "GPR"').fetchone()[0])


def _describe(path: Path) -> _RawSlice:
    """What the raw slice holds: its columns, whether dates are ISO, and its latest month."""
    with sqlite3.connect(path) as conn:
        columns = tuple(r[1] for r in conn.execute('PRAGMA table_info("GPR")'))
        sample = [r[0] for r in conn.execute(
            f'SELECT "{_DATE}" FROM "GPR" WHERE "{_DATE}" IS NOT NULL LIMIT 50')] \
            if _DATE in columns else []
        iso = P.is_iso_date(sample)
        parts = _parts(columns, iso)
        latest = None
        if parts is not None and _YEAR in columns:
            row = conn.execute(
                f'SELECT MAX(CAST("{_YEAR}" AS INTEGER) * 100 + {parts.month}) FROM "GPR"'
            ).fetchone()
            if row and row[0]:
                latest = (int(row[0]) // 100, int(row[0]) % 100)
    return _RawSlice(path=path, latest=latest, has_iso_date=iso, columns=columns)


def _parts(columns: Sequence[str], iso: bool) -> Optional[P.DateParts]:
    return P.date_parts_sql(date_column=_DATE if _DATE in columns else None, iso=iso,
                            month_name_column=_MONTH_NAME if _MONTH_NAME in columns else None)


def _governed_period(raw: _RawSlice, spec: BookSpec) -> WorkingBook:
    """The raw slice with the period applied (the raw slice itself when there is none)."""
    window = P.window_for(spec.choice, latest=raw.latest, year_pin=spec.year_pin)
    parts = _parts(raw.columns, raw.has_iso_date)
    needs_quarter = _QUARTER not in raw.columns and parts is not None
    if (window is None or parts is None) and not needs_quarter:
        _index(raw.path)
        return WorkingBook(engine=_engine(raw.path), window=None, latest=raw.latest)
    usable = window if parts is not None else None
    key = _key("period", _BUILD_VERSION, raw.path.name, usable.describe() if usable else "")
    path = raw.path.parent / f"book_{key}.db"
    with _lock(str(path)):
        if not path.exists():
            _build_period(raw, usable, parts, path)
        else:
            os.utime(path)
    return WorkingBook(engine=_engine(path), window=usable, latest=raw.latest)


def _build_period(raw: _RawSlice, window: Optional[P.PeriodWindow],
                  parts: Optional[P.DateParts], path: Path) -> None:
    """Relabel ``Year`` to the period year, drop rows outside every period, add ``Quarter``."""
    started = time.time()
    partial = path.with_suffix(".building")
    partial.unlink(missing_ok=True)
    others = [c for c in raw.columns if c != _YEAR]
    select = [f'"{c}"' for c in others]
    where = ""
    if window is not None and window.relabels:
        year = P.period_year_sql(window, parts, _YEAR)
        select.append(f'{year} AS "{_YEAR}"')
        where = f" WHERE {year} IS NOT NULL AND {year} <= {window.year}"
    else:
        select.append(f'"{_YEAR}"')
        if window is not None:                         # a range longer than a year
            md_date = f'substr("{_DATE}", 1, 10)' if raw.has_iso_date else None
            where = (f" WHERE {md_date} BETWEEN '{window.start.isoformat()}' "
                     f"AND '{window.end.isoformat()}'") if md_date else ""
    if _QUARTER not in raw.columns and parts is not None:
        select.append(f'{P.quarter_sql(parts.month)} AS "{_QUARTER}"')
    conn = _connect(partial)
    try:
        conn.execute("ATTACH DATABASE ? AS raw", (_read_only_uri(str(raw.path)),))
        conn.execute(f'CREATE TABLE "GPR" AS SELECT {", ".join(select)} FROM raw."GPR"{where}')
        for table in ("Peers", "Carriers"):
            if conn.execute("SELECT 1 FROM raw.sqlite_master WHERE type='table' AND name=?",
                            (table,)).fetchone():
                conn.execute(f'CREATE TABLE "{table}" AS SELECT * FROM raw."{table}"')
        conn.commit()
        conn.execute("DETACH DATABASE raw")
    finally:
        conn.close()
    partial.replace(path)
    _index(path)
    logger.info("studio book: %s applied in %.1fs (%s)",
                window.describe() if window else "quarter", time.time() - started, path.name)


_indexed: set = set()


def _index(path: Path) -> None:
    """The analytics indexes, plus the planner's statistics — once per book file."""
    if str(path) in _indexed:
        return
    from studio.indexes import ensure_indexes

    engine = _engine(path)
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for flow in ("gpr", "survey"):
        spec = get_flow_registry().get(flow)
        if spec is not None and spec.primary_table in tables:
            ensure_indexes(flow, engine)
    with engine.begin() as conn:
        conn.execute(text("ANALYZE"))
    _indexed.add(str(path))


_engines: Dict[str, Any] = {}


def _engine(path: Path) -> Any:
    """One engine per book file, reused by every query of every build that reads it."""
    key = str(path)
    if key not in _engines:
        _engines[key] = create_engine(f"sqlite:///{key}", poolclass=NullPool)
    return _engines[key]


def _prune(directory: Path, keep: int = _KEEP) -> None:
    """Drop the least recently used books beyond ``keep`` of each layer."""
    for prefix in ("raw_", "book_"):
        books = sorted(directory.glob(f"{prefix}*.db"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        for stale in books[keep:]:
            engine = _engines.pop(str(stale), None)
            if engine is not None:
                engine.dispose()
            _indexed.discard(str(stale))
            try:
                stale.unlink()
            except OSError:                             # still open elsewhere: next time
                pass


# ── an uploaded dataset: already in memory, relabelled in pandas ─────────────


def _frame_book(source: FrameSource, spec: BookSpec) -> WorkingBook:
    """The dataset with the period applied — no slice, it is already the size of one."""
    frame = source.table("GPR")
    latest = _frame_latest(frame)
    window = P.window_for(spec.choice, latest=latest, year_pin=spec.year_pin)
    book = WorkingBook(engine=_relabelled(source, frame, window), window=window, latest=latest)
    r12m = P.window_for(P.PeriodChoice(P.BASIS_R12M, date_to=spec.choice.date_to),
                        latest=latest, year_pin=spec.year_pin)
    book._r12m = lambda: WorkingBook(engine=_relabelled(source, frame, r12m),
                                     window=r12m, latest=latest)
    return book


def _frame_dates(frame) -> Any:
    """Each row's date as a pandas datetime — from the billing date, else year + month name."""
    import pandas as pd

    if _DATE in frame.columns:
        dates = pd.to_datetime(frame[_DATE], errors="coerce")
        if dates.notna().any():
            return dates
    if _MONTH_NAME in frame.columns and _YEAR in frame.columns:
        text_ = frame[_YEAR].astype(str) + "-" + frame[_MONTH_NAME].astype(str).str[:3] + "-15"
        return pd.to_datetime(text_, format="%Y-%b-%d", errors="coerce")
    return None


def _frame_latest(frame) -> Optional[Tuple[int, int]]:
    dates = _frame_dates(frame) if frame is not None and len(frame) else None
    if dates is None or not dates.notna().any():
        return None
    latest = dates.max()
    return int(latest.year), int(latest.month)


def _relabelled(source: FrameSource, frame, window: Optional[P.PeriodWindow]) -> FrameSource:
    """``source`` with GPR's ``Year`` relabelled to period years and a ``Quarter`` column."""
    import pandas as pd

    dates = _frame_dates(frame)
    if dates is None:
        return source
    out = frame.copy()
    if _QUARTER not in out.columns:
        out[_QUARTER] = "Q" + dates.dt.quarter.astype("Int64").astype(str)
    if window is not None and window.relabels:
        md = dates.dt.strftime("%m-%d")
        lo, hi = window.start.strftime("%m-%d"), window.end.strftime("%m-%d")
        year = dates.dt.year
        if window.crosses_year:
            period = (year + 1).where(md >= lo, year.where(md <= hi))
        else:
            period = year.where((md >= lo) & (md <= hi))
        keep = period.notna() & (period <= window.year)
        out = out[keep].copy()
        out[_YEAR] = period[keep].astype(int)
    elif window is not None:
        out = out[(dates >= pd.Timestamp(window.start)) & (dates <= pd.Timestamp(window.end))]
    tables = dict(source.tables)
    tables["GPR"] = out
    return FrameSource(tables=tables, label=f"{source.label}|{window.describe() if window else 'q'}")
