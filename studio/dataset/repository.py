"""Named saved datasets on disk — the Data tab's persistence boundary.

Each dataset is two files under the store directory:

    <id>.json     the ``DatasetRecord`` (name, profile, mappings, status)
    <id>.sqlite   the data itself — table ``upload`` holds the raw frame; the
                  mapping step later writes the canonical ``GPR`` table into the
                  SAME file, which then serves directly as the session engine
                  that takes precedence over the governed DB.

The browser store keeps only the dataset id, so uploads survive refreshes and
app restarts (the stale-tdoc failure mode does not apply here).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from logger import get_logger
from studio.dataset.ingest import profile_frame
from studio.dataset.model import DatasetRecord, record_from_json

logger = get_logger(__name__)

RAW_TABLE = "upload"
MAPPED_TABLE = "GPR"  # canonical table name the analytics primitives query

_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _store_dir() -> Path:
    override = os.getenv("STUDIO_DATASET_DIR")
    return Path(override) if override else Path(__file__).resolve().parent / "_store"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class DatasetRepository:
    """CRUD for saved datasets. All methods tolerate a missing/corrupt file."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else _store_dir()

    # ── paths ────────────────────────────────────────────────────────────────

    def _record_path(self, dataset_id: str) -> Path:
        return self.root / f"{dataset_id}.json"

    def db_path(self, dataset_id: str) -> Path:
        return self.root / f"{dataset_id}.sqlite"

    def engine(self, dataset_id: str):
        """A SQLAlchemy engine over this dataset's SQLite file (precedence seam).

        ``NullPool`` closes every connection as soon as it is returned — pooled
        connections would hold the file open and make Windows deletes fail."""
        return create_engine(f"sqlite:///{self.db_path(dataset_id)}", poolclass=NullPool)

    # ── write ────────────────────────────────────────────────────────────────

    def save(self, frame: pd.DataFrame, *, name: str, filename: str) -> DatasetRecord:
        """Persist a fresh upload: raw table + record. Returns the record."""
        self.root.mkdir(parents=True, exist_ok=True)
        dataset_id = _new_id()
        profile = profile_frame(frame)
        record = DatasetRecord(
            dataset_id=dataset_id,
            name=name or filename or dataset_id,
            filename=filename,
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            n_rows=profile.n_rows,
            n_cols=profile.n_cols,
            profile=profile,
        )
        frame.to_sql(RAW_TABLE, self.engine(dataset_id), if_exists="replace", index=False)
        self._write_record(record)
        # ASCII arrow: the → char breaks logging on cp1252 Windows consoles.
        logger.info("dataset saved: %s (%s rows) -> %s", record.name, record.n_rows, dataset_id)
        return record

    def update_record(self, record: DatasetRecord) -> None:
        """Overwrite a record's metadata (mapping edits, status changes)."""
        self._write_record(record)

    def _write_record(self, record: DatasetRecord) -> None:
        path = self._record_path(record.dataset_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record.to_json(), fh, indent=2)
        tmp.replace(path)  # atomic swap

    def delete(self, dataset_id: str) -> None:
        if not _ID_RE.match(dataset_id or ""):
            return
        for path in (self._record_path(dataset_id), self.db_path(dataset_id)):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:  # noqa: BLE001 — a locked file must not crash the app
                logger.warning("dataset delete failed for %s: %s", path.name, exc)

    # ── read ─────────────────────────────────────────────────────────────────

    def get(self, dataset_id: str) -> Optional[DatasetRecord]:
        if not _ID_RE.match(dataset_id or ""):
            return None
        try:
            with open(self._record_path(dataset_id), "r", encoding="utf-8") as fh:
                return record_from_json(json.load(fh))
        except (OSError, ValueError, KeyError):
            return None

    def list(self) -> List[DatasetRecord]:
        """Every saved dataset, newest first."""
        if not self.root.is_dir():
            return []
        records = []
        for path in self.root.glob("*.json"):
            record = self.get(path.stem)
            if record is not None:
                records.append(record)
        return sorted(records, key=lambda r: r.created, reverse=True)

    def load_frame(self, dataset_id: str, *, table: str = RAW_TABLE) -> Optional[pd.DataFrame]:
        if not _ID_RE.match(dataset_id or "") or not self.db_path(dataset_id).exists():
            return None
        try:
            return pd.read_sql_table(table, self.engine(dataset_id))
        except (ValueError, OSError) as exc:
            logger.warning("dataset frame load failed for %s: %s", dataset_id, exc)
            return None


@lru_cache(maxsize=1)
def get_repository() -> DatasetRepository:
    """The process-wide repository (default store dir; tests build their own)."""
    return DatasetRepository()
