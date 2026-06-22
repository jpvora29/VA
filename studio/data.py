"""Studio data access — engine resolution + DB-derived filter options.

LLM-free on purpose: this never imports ``core.initialization`` (which builds the
Azure/dspy clients). It resolves a SQLite engine from the same ``DB_PATH`` the live
app uses, falling back to a deterministic seed DB for local dev. Filter dropdown
options come straight from the DB (DISTINCT per column), so the form always
reflects the real data — no dependency on the legacy ``config`` package.
"""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import create_engine, text

from core.registry import get_flow_registry
from logger import get_logger

logger = get_logger(__name__)

# Persisted across launches so the expensive first-launch DISTINCT scans run once
# per DB, not on every start. Auto-invalidates when the DB file changes.
_CACHE_DIR = Path(__file__).resolve().parent / "_cache"


@lru_cache(maxsize=1)
def get_engine():
    """The Studio SQLite engine.

    Order: ``STUDIO_DB_PATH`` → ``DB_PATH`` (the live app's DB) → a local seed DB
    built on first use. The seed path keeps dev/CI runnable without the production
    data while exercising the exact same primitives.
    """
    path = os.getenv("STUDIO_DB_PATH") or os.getenv("DB_PATH")
    if path:
        logger.info("studio: using DB at %s", path)
        return create_engine(f"sqlite:///{path}")
    from studio.seed import ensure_seed_db

    seed = ensure_seed_db()
    logger.info("studio: no DB_PATH set; using seed DB at %s", seed)
    return create_engine(f"sqlite:///{seed}")


_OPTION_CAP = 100_000  # effectively "all" for a dropdown, but bounds a pathological column


def _distinct(engine, table: str, column: str, limit: int = _OPTION_CAP) -> List[Any]:
    # Cap the scan at the SQL layer: on a huge table we only need enough distinct
    # values to populate a dropdown, and we never want to materialise millions.
    sql = (
        f'SELECT v FROM (SELECT DISTINCT "{column}" AS v FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL) ORDER BY v LIMIT {int(limit)}'
    )
    try:
        with engine.connect() as conn:
            return [r.v for r in conn.execute(text(sql)).fetchall()]
    except Exception as exc:  # noqa: BLE001 - a missing column must not break the form
        logger.debug("distinct(%s.%s) failed: %s", table, column, exc)
        return []


@lru_cache(maxsize=128)
def _distinct_cached(table: str, column: str, limit: int = _OPTION_CAP) -> tuple:
    """Process-lifetime cache of a column's distinct values (the singleton engine).

    Distinct values are stable for a session, so the expensive scan runs once per
    column — the rest of the run is instant. Returns a tuple so it stays hashable.
    """
    return tuple(_distinct(get_engine(), table, column, limit))


@lru_cache(maxsize=256)
def _distinct_where(table: str, column: str, where_key: tuple, limit: int = _OPTION_CAP) -> tuple:
    """Cached distinct `column` values constrained by `where_key` (parametrised IN).

    `where_key` is a hashable tuple of ``(col, (v1, v2, …))`` pairs — the cascade
    constraints (e.g. Country values for a chosen Region)."""
    clauses = [f'"{column}" IS NOT NULL']
    params: Dict[str, Any] = {}
    for i, (col, vals) in enumerate(where_key):
        ph = []
        for j, v in enumerate(vals):
            k = f"w{i}_{j}"
            params[k] = v
            ph.append(f":{k}")
        clauses.append(f'"{col}" IN ({", ".join(ph)})')
    sql = (
        f'SELECT v FROM (SELECT DISTINCT "{column}" AS v FROM "{table}" '
        f'WHERE {" AND ".join(clauses)}) ORDER BY v LIMIT {int(limit)}'
    )
    try:
        with get_engine().connect() as conn:
            return tuple(r.v for r in conn.execute(text(sql), params).fetchall())
    except Exception as exc:  # noqa: BLE001
        logger.debug("distinct_where(%s.%s) failed: %s", table, column, exc)
        return ()


def dependent_options(
    flow: str, column: str, where: Dict[str, Any] | None = None
) -> List[Dict[str, Any]]:
    """`[{label, value}]` for `column`, optionally constrained by upstream selections.

    Columns are validated against the flow registry (injection guard). With no
    constraint this is the full (cached) distinct list — so it also serves the
    "give me the entire carrier list" case."""
    spec = get_flow_registry().get(flow)
    if spec is None or column not in spec.columns:
        return []
    pairs = []
    for col, val in (where or {}).items():
        if col not in spec.columns:
            continue
        vals = val if isinstance(val, (list, tuple, set)) else [val]
        vals = tuple(v for v in vals if v not in (None, "", "all", "All"))
        if vals:
            pairs.append((col, vals))
    key = tuple(sorted(pairs))
    values = (
        _distinct_where(spec.primary_table, column, key)
        if key
        else _distinct_cached(spec.primary_table, column)
    )
    return [{"label": str(v), "value": v} for v in values]


def peer_members(flow: str, carrier: str, *, country=None) -> List[str]:
    """The carrier's existing peers from the flow's Peers table (empty if none).

    Powers the custom-peers dialog: an empty list means "no peers exist for this
    carrier — pick custom peers instead"."""
    spec = get_flow_registry().get(flow)
    peer = getattr(spec, "peer_columns", None) if spec else None
    if not spec or not peer or not carrier:
        return []
    params: Dict[str, Any] = {"subject": carrier}
    where = [f'LOWER("{peer["key"]}") = LOWER(:subject)']
    ccol = peer.get("country")
    if ccol and country:
        cvals = list(country) if isinstance(country, (list, tuple, set)) else [country]
        cvals = [v for v in cvals if v not in (None, "", "all", "All")]
        if cvals:
            ph = []
            for j, v in enumerate(cvals):
                k = f"c{j}"
                params[k] = v
                ph.append(f"LOWER(:{k})")
            where.append(f'LOWER("{ccol}") IN ({", ".join(ph)})')
    sql = (
        f'SELECT DISTINCT "{peer["members"]}" AS m FROM "{peer["table"]}" '
        f'WHERE {" AND ".join(where)} ORDER BY m'
    )
    try:
        with get_engine().connect() as conn:
            return [r.m for r in conn.execute(text(sql), params).fetchall() if r.m]
    except Exception as exc:  # noqa: BLE001
        logger.debug("peer_members(%s) failed: %s", carrier, exc)
        return []


def filter_options(flow: str, *, engine=None) -> Dict[str, List[Dict[str, Any]]]:
    """`{column: [{label, value}]}` for every entity/temporal column of the flow.

    Driven by the flow registry so it stays in lock-step with the schema. Distinct
    values are cached per column (``_distinct_cached``) so a huge table is scanned
    once per column, not on every page load.
    """
    spec = get_flow_registry().get(flow)
    if spec is None:
        return {}
    cols = [c.name for c in spec.columns.values() if c.role in {"entity", "temporal"}]
    options: Dict[str, List[Dict[str, Any]]] = {}
    for col in cols:
        values = _distinct_cached(spec.primary_table, col)
        if values:
            options[col] = [{"label": str(v), "value": v} for v in values]
    return options


# ── persisted filter-option cache (fast app launch) ──────────────────────────


def _db_signature() -> str:
    """Fingerprint the active DB (path + size + mtime) so the on-disk cache is
    reused across launches but invalidated automatically when the data changes."""
    db = get_engine().url.database or "memory"
    try:
        st = os.stat(db)
        return f"{db}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        return str(db)


def _cache_file(flow: str) -> Path:
    sig = hashlib.blake2s(f"{flow}|{_db_signature()}".encode("utf-8"), digest_size=8).hexdigest()
    return _CACHE_DIR / f"filters_{flow}_{sig}.json"


def _read_disk_cache(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_disk_cache(path: Path, data: Dict[str, Any]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        tmp.replace(path)  # atomic swap
    except OSError as exc:  # noqa: BLE001 - cache is best-effort
        logger.debug("filter cache write failed: %s", exc)


_MEM_CACHE: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}


def cached_filter_options(flow: str) -> Dict[str, List[Dict[str, Any]]]:
    """Filter options with a three-tier cache: in-memory → on-disk → DB scan.

    The disk tier is the launch-speed win — after the first build for a given DB,
    every app start reads a tiny JSON instead of re-scanning a huge table."""
    path = _cache_file(flow)
    key = str(path)
    if key in _MEM_CACHE:
        return _MEM_CACHE[key]
    disk = _read_disk_cache(path)
    if disk is not None:
        logger.info("studio: filter options from disk cache (%s)", path.name)
        _MEM_CACHE[key] = disk
        return disk
    logger.info("studio: building filter options (first launch for this DB)…")
    opts = filter_options(flow)
    _MEM_CACHE[key] = opts
    _write_disk_cache(path, opts)
    return opts


def warm_filter_cache(flow: str = "gpr") -> str:
    """Build the on-disk filter cache now so the next app launch is instant.

    Run offline once (see ``python -m studio.warm_cache``)."""
    cached_filter_options(flow)
    return str(_cache_file(flow))


def ensure_filter_indexes(flow: str = "gpr") -> List[str]:
    """Create a single-column index on each filter column (one-time).

    OPT-IN: this WRITES to the DB and, on a huge table, can take minutes and grow
    the file — so it is never run automatically. It makes the first DISTINCT build
    (and any cache rebuild after a data refresh) dramatically faster."""
    spec = get_flow_registry().get(flow)
    if spec is None:
        return []
    cols = [c.name for c in spec.columns.values() if c.role in {"entity", "temporal"}]
    made: List[str] = []
    with get_engine().begin() as conn:
        for col in cols:
            idx = f"ix_studio_{spec.primary_table}_{col}"
            try:
                conn.execute(
                    text(f'CREATE INDEX IF NOT EXISTS "{idx}" ON "{spec.primary_table}" ("{col}")')
                )
                made.append(idx)
            except Exception as exc:  # noqa: BLE001
                logger.warning("studio: index %s failed: %s", idx, exc)
    return made
