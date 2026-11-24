"""Append usage rows to one person's Excel workbook.

One workbook per person, so every file has exactly one writer — that is what lets the
folder sit somewhere shared (a OneDrive folder) without conflict copies.

A workbook that is open in Excel on the same machine is locked. Rows that cannot be
written then wait in a ``.pending.jsonl`` file beside it and go in with the next
write that succeeds, so closing Excel never loses usage.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

from core.usage_metrics.events import COLUMNS

SHEET = "Usage"
MAX_CELL_CHARS = 32_000  # Excel's hard limit is 32,767 per cell
_COLUMN_WIDTHS = {
    "Timestamp": 20,
    "User ID": 9,
    "Email": 30,
    "Username": 24,
    "Tab": 11,
    "Action": 18,
    "Studio selections": 60,
    "Question": 50,
    "Reply": 80,
    "Uploaded files": 40,
    "Status": 10,
    "Notes": 40,
}
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9@._-]+")


def workbook_path(folder: Path, file_key: str) -> Path:
    """``<folder>/<file_key>.xlsx`` with anything unsafe in a filename replaced."""
    safe = _UNSAFE_FILENAME.sub("_", file_key).strip("._") or "anonymous"
    return folder / f"{safe}.xlsx"


def pending_path(path: Path) -> Path:
    return path.with_suffix(".pending.jsonl")


def append_rows(path: Path, rows: Sequence[Sequence[Any]]) -> None:
    """Append ``rows`` (and any rows left pending) to ``path``.

    On a locked workbook the rows are parked in the pending file instead and the
    ``PermissionError`` is re-raised so the caller can log it.
    """
    all_rows = [*read_pending(path), *rows]
    try:
        write_rows(path, all_rows)
    except PermissionError:
        write_pending(path, all_rows)
        raise
    clear_pending(path)


def write_rows(path: Path, rows: Sequence[Sequence[Any]]) -> None:
    """Open (or create) the workbook, append, and save through a temp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    book = load_workbook(path) if path.exists() else new_workbook()
    sheet = book[SHEET]
    for row in rows:
        sheet.append([clean_cell(value) for value in row])
        mark_text_cells(sheet[sheet.max_row])
    sheet.auto_filter.ref = sheet.dimensions
    temp = path.with_name(f"~{path.stem}.tmp.xlsx")
    book.save(temp)
    os.replace(temp, path)


def new_workbook() -> Workbook:
    """An empty usage workbook: bold frozen header row, sized columns."""
    book = Workbook()
    sheet = book.active
    sheet.title = SHEET
    sheet.append(list(COLUMNS))
    header_fill = PatternFill("solid", fgColor="DDE4EE")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
        sheet.column_dimensions[cell.column_letter].width = _COLUMN_WIDTHS.get(
            cell.value,
            16,
        )
    sheet.freeze_panes = "A2"
    return book


def clean_cell(value: Any) -> Any:
    """A value Excel will accept: no control characters, no over-long text."""
    if not isinstance(value, str):
        return value
    text = ILLEGAL_CHARACTERS_RE.sub("", value)
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + " …[truncated]"
    return text


def mark_text_cells(cells: Sequence[Any]) -> None:
    """Keep user text as text: a question starting with '=' is not a formula."""
    wrap = Alignment(wrap_text=True, vertical="top")
    for cell in cells:
        if isinstance(cell.value, str):
            cell.data_type = "s"
            cell.alignment = wrap
        elif isinstance(cell.value, datetime):
            cell.number_format = "yyyy-mm-dd hh:mm:ss"
            cell.alignment = Alignment(vertical="top")


# ── pending rows ──────────────────────────────────────────────────────────────


def read_pending(path: Path) -> list[list[Any]]:
    pending = pending_path(path)
    if not pending.exists():
        return []
    rows = []
    for line in pending.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(_decode_row(json.loads(line)))
    return rows


def write_pending(path: Path, rows: Sequence[Sequence[Any]]) -> None:
    pending = pending_path(path)
    pending.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_encode_row(row), ensure_ascii=False) for row in rows]
    pending.write_text("\n".join(lines) + "\n", encoding="utf-8")


def clear_pending(path: Path) -> None:
    pending_path(path).unlink(missing_ok=True)


def _encode_row(row: Sequence[Any]) -> list[Any]:
    return [
        {"datetime": value.isoformat()} if isinstance(value, datetime) else value
        for value in row
    ]


def _decode_row(row: Sequence[Any]) -> list[Any]:
    return [
        datetime.fromisoformat(value["datetime"])
        if isinstance(value, dict) and "datetime" in value
        else value
        for value in row
    ]
