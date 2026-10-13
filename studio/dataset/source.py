"""The precedence seam: which data source drives Setup and Generate.

A submitted custom dataset takes precedence over the governed DB — its SQLite
(holding the materialized ``GPR`` table) becomes the engine, and Setup's filter
options derive from it. Everything resolves lazily from the browser store's
``{"source", "active"}`` so nothing here touches an engine at import time
(see the ``.env``-before-imports note in ``authoring_app.py``).
"""
from __future__ import annotations

import threading
import time
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from logger import get_logger
from studio.dataset.model import DatasetRecord
from studio.dataset.repository import MAPPED_TABLE, get_repository

logger = get_logger(__name__)

# The peer group stays governed by design, so an uploaded dataset carries only a
# schema-only Peers table (see ``materialize._ensure_empty_peers``).
_PEERS_TABLE = "Peers"


def dataset_in_use(store: Optional[Mapping[str, Any]]) -> Optional[DatasetRecord]:
    """The submitted dataset record when the user chose custom data, else None."""
    store = store or {}
    if store.get("source") != "custom":
        return None
    record = get_repository().get(store.get("active") or "")
    if record is None or record.status != "submitted":
        return None
    if not get_repository().db_path(record.dataset_id).exists():
        logger.warning("submitted dataset %s lost its data file", record.dataset_id)
        return None
    return record


def dataset_engine(dataset_id: str):
    """The engine over a submitted dataset's SQLite (its GPR table is canonical)."""
    return get_repository().engine(dataset_id)


@lru_cache(maxsize=8)
def dataset_source(dataset_id: str):
    """The dataset as a :class:`~core.analytics.frames.FrameSource` — the analytics source.

    Uploaded data does not answer SQL well. Its table carries only the columns the user
    actually had, so every primitive cutting by one they did not upload (industry, cover
    line, billing date…) failed with "no such column" and was swallowed into an empty
    section — which is how a full deck came out a shell. The pandas executor
    (:mod:`core.analytics.pandas_library`) treats an absent column as an absent CUT and
    keeps the rest of the deck, and it reads the data once instead of per query.

    Cached per dataset: the frames are rebuilt only when the dataset is re-materialized
    (``use_for_deck`` clears this).
    """
    from core.analytics.frames import frame_source
    from studio.dataset.repository import RAW_TABLE

    repo = get_repository()
    tables = {
        MAPPED_TABLE: repo.load_frame(dataset_id, table=MAPPED_TABLE),
        _PEERS_TABLE: repo.load_frame(dataset_id, table=_PEERS_TABLE),
    }
    loaded = {name: frame for name, frame in tables.items() if frame is not None}
    if MAPPED_TABLE not in loaded:
        logger.warning("dataset %s has no %s table — falling back to the raw upload",
                       dataset_id, MAPPED_TABLE)
        raw = repo.load_frame(dataset_id, table=RAW_TABLE)
        if raw is not None:
            loaded[MAPPED_TABLE] = raw
    return frame_source(loaded, label=dataset_id)


def dataset_frame(dataset_id: str) -> Optional[pd.DataFrame]:
    """The dataset's materialized table — what every Setup panel reads it from.

    The repository's SHARED frame, not a copy: nothing on the Setup path reshapes it, and a
    copy of a million-row upload on every call was most of a filter change.
    """
    return get_repository().read_frame(dataset_id, table=MAPPED_TABLE)


def dataset_version(dataset_id: str):
    """The dataset file's version — what every cache derived from its frame is keyed on."""
    return get_repository().version(dataset_id)


def dataset_measure(frame: Optional[pd.DataFrame]) -> Optional[str]:
    """The measure the dataset's cube carries — the one the Setup preview rolls up — or None
    when the frame does not hold it (the cascade then builds a cube without one)."""
    from studio.data import cube_measure

    measure = cube_measure("gpr")
    return measure if frame is not None and measure in frame.columns else None


def dataset_filter_options(
    dataset_id: str, friendly_columns: Mapping[str, str]
) -> Dict[str, List[Dict[str, Any]]]:
    """Setup filter options derived from the materialized table.

    Same shape as ``studio.authoring.generate._friendly_options`` — friendly
    form id → ``[{label, value}]`` — but distincts come from the user's data,
    so every dropdown reflects exactly what they uploaded. Read off the same cube
    the cascade uses (an unfiltered cascade), not a ``unique()`` per column per render.
    """
    if dataset_frame(dataset_id) is None:
        return {}
    cascaded = dataset_cascade_options(dataset_id, tuple(friendly_columns.values()))
    return {fid: cascaded.get(column, []) for fid, column in friendly_columns.items()}


def dataset_cascade_options(
    dataset_id: str, columns: Sequence[str], selected: Optional[Mapping[str, Any]] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """``{column: [{label, value}]}`` for a whole cascade over an uploaded dataset.

    The pandas twin of :func:`studio.data.cascade_options`: one cached distinct-combination
    cube answers every column, instead of re-filtering the frame once per column. Like the
    SQL twin the cube spans the FULL filter vocabulary, so asking for one column still
    honours the constraints on the others.
    """
    from studio import filter_cube
    from studio.data import cube_columns

    frame = dataset_frame(dataset_id)
    if frame is None:
        return {}
    spanned = tuple(c for c in cube_columns("gpr") if c in frame.columns)
    cube = filter_cube.frame_cube(dataset_id, frame, spanned,
                                  version=dataset_version(dataset_id),
                                  measure=dataset_measure(frame))
    if cube is not None and not cube.can_answer(selected or {}):
        # A constraint the cube does not span would be dropped, widening every list. Fall
        # back to the per-column frame scan, which honours it (the SQL twin does the same).
        cube = None
    selected = {c: v for c, v in (selected or {}).items() if c in spanned}
    cascaded = filter_cube.cascade(cube, selected)

    out: Dict[str, List[Dict[str, Any]]] = {}
    for column in columns:
        values = cascaded.get(column)
        if values is None:
            where = {c: v for c, v in selected.items() if c != column}
            out[column] = dataset_dependent_options(dataset_id, column, where)
        else:
            # Blank cells are not an option (the per-column path drops them too).
            out[column] = [{"label": str(v), "value": _plain(v)} for v in values
                           if not pd.isna(v)]
    return out


def dataset_dependent_options(
    dataset_id: str,
    column: str,
    where: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """`[{label, value}]` for one column, constrained by the other selections —
    the pandas twin of ``studio.data.dependent_options`` for custom datasets."""
    frame = dataset_frame(dataset_id)
    if frame is None or column not in frame.columns:
        return []
    for col, val in (where or {}).items():
        if col not in frame.columns:
            continue
        vals = [v for v in (val if isinstance(val, (list, tuple, set)) else [val])
                if v not in (None, "", "all", "All")]
        if vals:
            frame = frame[frame[col].astype(str).isin([str(v) for v in vals])]
    values = sorted(frame[column].dropna().unique(), key=str)
    return [{"label": str(v), "value": _plain(v)} for v in values]


def _plain(value: Any) -> Any:
    """Numpy scalars → plain python so Dash serializes dropdown values cleanly."""
    return value.item() if hasattr(value, "item") else value


def dataset_quarters_in_scope(dataset_id: str, where: Mapping[str, Any]) -> Optional[List[str]]:
    """The quarter labels an uploaded dataset holds under ``where`` — ``None`` when it
    records no period finer than a year (the form then offers every quarter)."""
    from studio.quarter_scope import quarters_in_keyed

    columns, rows = _quarter_rows(dataset_id, dataset_version(dataset_id))
    return quarters_in_keyed(rows, columns, where) if rows else None


@lru_cache(maxsize=8)
def _quarter_rows(dataset_id: str, _version) -> tuple:
    """The dataset's distinct ``(scope columns…, quarter)`` rows, derived once per version
    and already keyed for comparison (:func:`studio.quarter_scope.keyed_rows`).

    They do not depend on the selection, yet were re-derived — one Python call per frame row
    — on every filter change: over a second of each change on a million-row upload.
    """
    from studio.quarter_scope import frame_quarter_rows, keyed_rows

    frame = dataset_frame(dataset_id)
    if frame is None:
        return (), []
    columns, rows = frame_quarter_rows(frame)
    return columns, keyed_rows(rows)


def dataset_quarter_labels(dataset_id: str) -> List[str]:
    """The uploaded dataset's own ``Quarter`` labels — ``[]`` when it has no such column."""
    return list(_quarter_labels(dataset_id, dataset_version(dataset_id)))


@lru_cache(maxsize=8)
def _quarter_labels(dataset_id: str, _version) -> tuple:
    frame = dataset_frame(dataset_id)
    if frame is None or "Quarter" not in frame.columns:
        return ()
    return tuple(sorted({str(v) for v in frame["Quarter"].dropna() if str(v).strip()}))


def dataset_latest_month(dataset_id: str) -> Optional[tuple]:
    """``(year, month)`` of the dataset's latest billing, or None — read once per version.

    The Setup period sentence asks for it on every filter change, and reading it means
    parsing every row's date.
    """
    return _latest_month(dataset_id, dataset_version(dataset_id))


@lru_cache(maxsize=8)
def _latest_month(dataset_id: str, _version) -> Optional[tuple]:
    from studio.book import _frame_latest

    return _frame_latest(dataset_frame(dataset_id))


# ── warming (so the first Setup visit after Use-for-deck does not pay) ───────


def warm_dataset(dataset_id: str) -> threading.Thread:
    """Prepare everything Setup reads from a dataset, on a background thread.

    Called the moment a dataset is submitted for the deck: the author is on their way to
    Setup, and the frame read, the cube and the period facts are each seconds on a large
    upload. Every one of them is cached and lock-guarded, so a Setup callback that arrives
    mid-warm waits for the same work instead of starting its own.
    """
    thread = threading.Thread(target=_warm, args=(dataset_id,), daemon=True,
                              name=f"warm-dataset-{dataset_id}")
    thread.start()
    return thread


def _warm(dataset_id: str) -> None:
    started = time.time()
    try:
        dataset_cascade_options(dataset_id, ())     # the frame, then the one shared cube
        _quarter_rows(dataset_id, dataset_version(dataset_id))
        dataset_latest_month(dataset_id)
    except Exception as exc:  # noqa: BLE001 - warming is an optimisation; Setup still works
        logger.warning("dataset %s warm-up failed: %s", dataset_id, exc)
        return
    logger.info("dataset %s ready for Setup in %.1fs", dataset_id, time.time() - started)
