"""Turn an uploaded file into a DataFrame and a per-column profile.

Pure transformation: bytes in, frame + profile out. No disk, no engine — the
repository owns persistence. Parsing dispatches on file extension.
"""
from __future__ import annotations

import io
from typing import Callable, Dict, Tuple

import pandas as pd

from studio.dataset.model import ColumnProfile, DatasetProfile

_SAMPLE_VALUES = 5
_MAX_ROWS = 100_000  # agreed upload ceiling — beyond this we truncate, loudly


def _read_csv(data: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(data))


def _read_excel(data: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(data))


_READERS: Dict[str, Callable[[bytes], pd.DataFrame]] = {
    ".csv": _read_csv,
    ".xlsx": _read_excel,
    ".xls": _read_excel,
}

SUPPORTED_EXTENSIONS = tuple(_READERS)


def _extension(filename: str) -> str:
    name = (filename or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def read_upload(filename: str, data: bytes) -> Tuple[pd.DataFrame, bool]:
    """Parse an uploaded file. Returns ``(frame, truncated)``.

    Raises ``ValueError`` for unsupported extensions so the callback can show a
    friendly message instead of a stack trace.
    """
    reader = _READERS.get(_extension(filename))
    if reader is None:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise ValueError(f"Unsupported file type {filename!r} — expected one of: {supported}")
    frame = reader(data)
    frame.columns = [str(c).strip() for c in frame.columns]
    truncated = len(frame) > _MAX_ROWS
    if truncated:
        frame = frame.head(_MAX_ROWS)
    return frame, truncated


def _column_kind(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    return "text"


def _profile_column(name: str, series: pd.Series) -> ColumnProfile:
    n = len(series)
    nulls = int(series.isna().sum())
    distinct = series.dropna().unique()
    sample = tuple(str(v) for v in distinct[:_SAMPLE_VALUES])
    return ColumnProfile(
        name=name,
        kind=_column_kind(series),
        null_pct=round(100.0 * nulls / n, 1) if n else 0.0,
        n_distinct=len(distinct),
        sample=sample,
    )


def profile_frame(frame: pd.DataFrame) -> DatasetProfile:
    """Shape summary of the whole frame — pure, deterministic."""
    columns = tuple(_profile_column(str(c), frame[c]) for c in frame.columns)
    return DatasetProfile(n_rows=len(frame), n_cols=len(frame.columns), columns=columns)
