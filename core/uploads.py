"""Uploaded files, from the browser to a workspace's run directory.

Dash hands an upload over as a ``data:<mime>;base64,<payload>`` string. Keeping that
string in a ``dcc.Store`` would ship a whole deck to the browser and back again on
every callback that reads it, so an upload is written to disk the moment it arrives
and the store carries only ``{name, path}``.

Staged files live outside any run directory until Generate is pressed, because at
upload time there is no run yet — the user may still change the document type, or add
a second deck.

Two workspaces stage uploads this way (MoM and Recap), so the mechanics live here and
each workspace binds them to its own runs directory: :mod:`mom.uploads`,
:mod:`recap.uploads`. Nothing here knows what a run is.
"""
from __future__ import annotations

import base64
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

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


def safe_name(filename: str) -> str:
    """A filename safe to join onto a directory — never a path, never empty."""
    cleaned = _SAFE.sub("_", Path(filename or "").name).strip(" .")
    return cleaned or "upload"


def decode(contents: str) -> bytes:
    """The bytes behind a ``dcc.Upload`` contents string."""
    _, _, payload = (contents or "").partition("base64,")
    return base64.b64decode(payload or "")


def check_extension(name: str, accept: str) -> None:
    """Raise :class:`UploadRejected` unless ``name`` carries an accepted extension.

    ``accept`` is the same comma-separated list the upload zone advertises, so the
    check the browser does is repeated here — a drag-and-drop can bypass the input's
    ``accept`` attribute entirely.
    """
    allowed = {ext.strip().lower() for ext in accept.split(",") if ext.strip()}
    if allowed and Path(name).suffix.lower() not in allowed:
        raise UploadRejected(f"{name} is not {' or '.join(sorted(allowed))}.")


def stage_upload(contents: str, filename: str, accept: str, *, staging_root: Path) -> StagedFile:
    """Write one upload under ``staging_root``, rejecting a format we cannot read.

    Each upload gets its own directory, so two files with the same name — a deck the
    user re-picked, two quarters both called ``QBR.pptx`` — never overwrite each other.
    """
    name = safe_name(filename)
    check_extension(name, accept)

    directory = staging_root / uuid.uuid4().hex[:12]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(decode(contents))
    return StagedFile(name=name, path=path)


def adopt(staged: StagedFile, inputs_dir: Path) -> Path:
    """Copy a staged file into a run's inputs, so the run directory is self-contained."""
    destination = inputs_dir / staged.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged.path, destination)
    return destination
