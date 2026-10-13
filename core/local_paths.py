"""Where the app keeps the files it writes at runtime.

The code is shared through OneDrive, so anything the app WRITES must live outside the
project folder: a synced folder turns two users' writes to one file into conflict
copies, and a live SQLite file (with its ``-wal``/``-shm``/``-journal`` companions)
into a corrupt one. Every runtime store therefore defaults to one per-user, unsynced
folder — ``%LOCALAPPDATA%\\VA`` on Windows — and each keeps its own env override.
"""
from __future__ import annotations

import os
from pathlib import Path


def local_data_dir() -> Path:
    """This user's unsynced app-data folder (``%LOCALAPPDATA%\\VA`` on Windows)."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "VA"
