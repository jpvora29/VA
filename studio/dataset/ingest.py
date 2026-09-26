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
# The upload ceiling — beyond this we truncate, loudly. One million rows: an uploaded book
# runs on the in-memory pandas executor, which answers a deck at that size in minutes.
# ``STUDIO_UPLOAD_MAX_ROWS`` moves it for a machine with the memory to go further.
_DEFAULT_MAX_ROWS = 1_000_000


def max_rows() -> int:
    """The row ceiling, read at call time (the app loads ``.env`` after importing this)."""
    import os

    raw = os.getenv("STUDIO_UPLOAD_MAX_ROWS", "").strip()
    try:
        return max(1, int(raw)) if raw else _DEFAULT_MAX_ROWS
    except ValueError:
        return _DEFAULT_MAX_ROWS


def _read_csv(data: bytes) -> pd.DataFrame:
    # low_memory=False: a million-row file read in chunks can type one column two ways.
    return pd.read_csv(io.BytesIO(data), low_memory=False)


def _read_openpyxl(data: bytes) -> pd.DataFrame:
    # Pass the engine explicitly: we dispatch on the *filename* extension, and a
    # BytesIO has no name for pandas to sniff.
    return pd.read_excel(io.BytesIO(data), engine="openpyxl")


def _read_xlrd(data: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(data), engine="xlrd")


def _read_pyxlsb(data: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(data), engine="pyxlsb")


_READERS: Dict[str, Callable[[bytes], pd.DataFrame]] = {
    ".csv": _read_csv,
    ".xlsx": _read_openpyxl,
    ".xlsm": _read_openpyxl,   # macro-enabled workbook — same OOXML zip
    ".xls": _read_xlrd,
    ".xlsb": _read_pyxlsb,
}

SUPPORTED_EXTENSIONS = tuple(_READERS)

# Extensions whose reader needs a third-party engine that may not be installed.
# Naming the package beats "is it a valid spreadsheet?" — the file is fine, we aren't.
_ENGINE_PACKAGE: Dict[str, str] = {".xls": "xlrd", ".xlsb": "pyxlsb"}

# Leading bytes → what the file actually is, for when the extension lies.
_MAGIC: Tuple[Tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "an OOXML workbook (.xlsx/.xlsm)"),
    (b"\xd0\xcf\x11\xe0", "a legacy .xls workbook, or a password-protected one"),
    (b"<", "an HTML or XML file saved with a spreadsheet name"),
    (b"{\\rtf", "an RTF document"),
    (b"%PDF", "a PDF"),
)


def _extension(filename: str) -> str:
    name = (filename or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def _detected_kind(data: bytes) -> str:
    """What the bytes look like, regardless of what the file is called."""
    for magic, label in _MAGIC:
        if data.startswith(magic):
            return label
    return ""


def unreadable_message(filename: str, ext: str, data: bytes, exc: Exception) -> str:
    """Why this upload could not be parsed, in words the user can act on.

    Every distinct cause used to collapse into one "is it a valid spreadsheet?"
    line, which reads as "wrong file type" even when the type is right.
    """
    if not data:
        return (
            f"{filename!r} arrived empty (0 bytes). If it lives in OneDrive or "
            "SharePoint, open it once so it downloads locally, then upload again."
        )
    kind = _detected_kind(data)
    if kind and ext in (".xlsx", ".xlsm") and not data.startswith(b"PK\x03\x04"):
        return (
            f"{filename!r} is named {ext} but its contents are {kind}. Open it in "
            "Excel and use Save As → Excel Workbook (.xlsx), then upload again."
        )
    if ext == ".csv":
        return f"{filename!r} could not be parsed as CSV: {exc}"
    return f"{filename!r} could not be read: {exc}"


def _parse(ext: str, filename: str, data: bytes) -> pd.DataFrame:
    """Run the reader for ``ext``, turning every failure into a ``ValueError``
    whose message is fit to show the user."""
    try:
        return _READERS[ext](data)
    except ImportError:
        package = _ENGINE_PACKAGE.get(ext, "")
        raise ValueError(
            f"{ext} files need the optional {package!r} package, which isn't installed. "
            f"Install it (pip install {package}) or re-save the file as .xlsx."
        ) from None
    except ValueError as exc:
        raise ValueError(unreadable_message(filename, ext, data, exc)) from exc
    except Exception as exc:  # noqa: BLE001 — engine errors are many; the message is what matters
        raise ValueError(unreadable_message(filename, ext, data, exc)) from exc


def read_upload(filename: str, data: bytes) -> Tuple[pd.DataFrame, bool]:
    """Parse an uploaded file. Returns ``(frame, truncated)``.

    Raises ``ValueError`` — with a message written for the user — for every
    failure, so the callback can show it instead of a stack trace or a guess.
    """
    ext = _extension(filename)
    if ext not in _READERS:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise ValueError(f"Unsupported file type {filename!r} — expected one of: {supported}")
    frame = _parse(ext, filename, data)
    frame.columns = [str(c).strip() for c in frame.columns]
    ceiling = max_rows()
    truncated = len(frame) > ceiling
    if truncated:
        frame = frame.head(ceiling)
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
