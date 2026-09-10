"""MoM's uploads: the shared staging mechanics, bound to MoM's runs directory.

The mechanics — decode, sanitise the name, reject a format we cannot read, copy into
a run — are in :mod:`core.uploads`, because Recap stages uploads the same way. What
is MoM's own is *where*: under ``mom.config.runs_root``, so a staged file and the run
that adopts it sit in the same tree.
"""
from __future__ import annotations

from pathlib import Path

from core.uploads import StagedFile, UploadRejected, adopt as _adopt, decode, safe_name
from core.uploads import stage_upload as _stage_upload
from mom.config import RunPaths, runs_root

__all__ = [
    "StagedFile",
    "UploadRejected",
    "adopt",
    "decode",
    "safe_name",
    "stage_upload",
    "staging_dir",
]


def staging_dir() -> Path:
    return runs_root() / "_uploads"


def stage_upload(contents: str, filename: str, accept: str) -> StagedFile:
    """Write an upload to MoM's staging directory, rejecting a format it cannot read."""
    return _stage_upload(contents, filename, accept, staging_root=staging_dir())


def adopt(staged: StagedFile, paths: RunPaths) -> Path:
    """Copy a staged file into a run's inputs, so the run directory is self-contained."""
    return _adopt(staged, paths.inputs)
