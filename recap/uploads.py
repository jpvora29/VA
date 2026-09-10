"""Recap's uploads: the shared staging mechanics, bound to Recap's runs directory.

The mechanics live in :mod:`core.uploads`. What is Recap's own is *where* (under
``recap.config.runs_root``) and *how many*: a recap reads one or more decks, so the
workspace stages a list and a run adopts all of them.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from core.uploads import StagedFile, UploadRejected, adopt as _adopt, decode, safe_name
from core.uploads import stage_upload as _stage_upload
from recap.config import RunPaths, runs_root

__all__ = [
    "StagedFile",
    "UploadRejected",
    "adopt_all",
    "decode",
    "safe_name",
    "stage_upload",
    "staged_from_store",
    "staging_dir",
]

#: The only format a QBR deck arrives in.
ACCEPT = ".pptx"


def staging_dir() -> Path:
    return runs_root() / "_uploads"


def stage_upload(contents: str, filename: str, accept: str = ACCEPT) -> StagedFile:
    """Write one uploaded deck to Recap's staging directory."""
    return _stage_upload(contents, filename, accept, staging_root=staging_dir())


def staged_from_store(rows: Sequence[dict] | None) -> List[StagedFile]:
    """The decks a store holds, dropping any whose file has since gone away.

    The store outlives the files it names — a staged upload is on disk, and a restarted
    server or a cleaned temp directory takes it with it. Reading through this function
    means a run is never started against a path that is no longer there.
    """
    staged = [StagedFile.from_store(row) for row in rows or []]
    return [file for file in staged if file is not None and file.exists()]


def adopt_all(staged: Sequence[StagedFile], paths: RunPaths) -> List[Path]:
    """Copy every staged deck into the run's inputs, in the order the user added them."""
    return [_adopt(file, paths.inputs) for file in staged]
