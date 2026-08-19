"""The precedence seam: which data source drives Setup and Generate.

A submitted custom dataset takes precedence over the governed DB — its SQLite
(holding the materialized ``GPR`` table) becomes the engine, and Setup's filter
options derive from it. Everything resolves lazily from the browser store's
``{"source", "active"}`` so nothing here touches an engine at import time
(see the ``.env``-before-imports note in ``authoring_app.py``).
"""
from __future__ import annotations

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
    """The dataset's materialized table — what every Setup panel reads it from."""
    return get_repository().load_frame(dataset_id, table=MAPPED_TABLE)


def dataset_filter_options(
    dataset_id: str, friendly_columns: Mapping[str, str]
) -> Dict[str, List[Dict[str, Any]]]:
    """Setup filter options derived from the materialized table.

    Same shape as ``studio.authoring.generate._friendly_options`` — friendly
    form id → ``[{label, value}]`` — but distincts come from the user's data,
    so every dropdown reflects exactly what they uploaded."""
    frame = dataset_frame(dataset_id)
    if frame is None:
        return {}
    options: Dict[str, List[Dict[str, Any]]] = {}
    for fid, column in friendly_columns.items():
        if column not in frame.columns:
            options[fid] = []
            continue
        values = sorted(frame[column].dropna().unique(), key=str)
        options[fid] = [{"label": str(v), "value": _plain(v)} for v in values]
    return options


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
    cube = filter_cube.frame_cube(dataset_id, frame, spanned)
    selected = {c: v for c, v in (selected or {}).items() if c in spanned}
    cascaded = filter_cube.cascade(cube, selected)

    out: Dict[str, List[Dict[str, Any]]] = {}
    for column in columns:
        values = cascaded.get(column)
        if values is None:
            where = {c: v for c, v in selected.items() if c != column}
            out[column] = dataset_dependent_options(dataset_id, column, where)
        else:
            out[column] = [{"label": str(v), "value": _plain(v)} for v in values]
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
