"""Uploaded files, from the browser to a run directory.

Dash hands an upload over as a ``data:<mime>;base64,<payload>`` string. Keeping that
string in a ``dcc.Store`` would ship a whole deck to the browser and back again on
every callback, so an upload is written to disk the moment it arrives and the store
carries only its path.

Staged files live outside any run directory until Generate is pressed, because at
upload time there is no run yet — the user may still change the document type.
"""
from __future__ import annotations

import base64
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from mom.config import RunPaths, runs_root

# Anything else in a filename came from the client, not from us.
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


class UploadRejected(ValueError):
    """The uploaded file is not one this workspace accepts."""


@dataclass(frozen=True)
class StagedFile:
    """An upload saved to disk, waiting for a run to claim it."""

    name: str          # the name the user recognises
    path: Path         # where it actually is

    def as_store(self) -> dict:
        return {"name": self.name, "path": str(self.path)}

    @classmethod
    def from_store(cls, data: dict | None) -> "StagedFile | None":
        if not data or not data.get("path"):
            return None
        return cls(name=data.get("name", ""), path=Path(data["path"]))

    def exists(self) -> bool:
        return self.path.is_file()


def staging_dir() -> Path:
    return runs_root() / "_uploads"


def safe_name(filename: str) -> str:
    """A filename safe to join onto a directory — never a path, never empty."""
    cleaned = _SAFE.sub("_", Path(filename or "").name).strip(" .")
    return cleaned or "upload"


def decode(contents: str) -> bytes:
    """The bytes behind a ``dcc.Upload`` contents string."""
    _, _, payload = (contents or "").partition("base64,")
    return base64.b64decode(payload or "")


def stage_upload(contents: str, filename: str, accept: str) -> StagedFile:
    """Write an upload to the staging directory, rejecting an extension we cannot read.

    ``accept`` is the mode's comma-separated extension list, so the check the browser
    does is repeated here — a drag-and-drop can bypass the input's ``accept``.
    """
    name = safe_name(filename)
    allowed = {ext.strip().lower() for ext in accept.split(",") if ext.strip()}
    if allowed and Path(name).suffix.lower() not in allowed:
        raise UploadRejected(f"{name} is not {' or '.join(sorted(allowed))}.")

    directory = staging_dir() / uuid.uuid4().hex[:12]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(decode(contents))
    return StagedFile(name=name, path=path)


def adopt(staged: StagedFile, paths: RunPaths) -> Path:
    """Copy a staged file into a run's inputs, so the run directory is self-contained."""
    destination = paths.inputs / staged.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged.path, destination)
    return destination
