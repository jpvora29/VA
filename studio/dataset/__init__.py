"""User-uploaded datasets for the Studio Data tab.

The upstream step of the authoring flow: a user uploads a spreadsheet, maps its
columns onto the canonical GPR schema (HITL), shapes it (computed columns,
pivots), and the submitted result takes precedence over the governed DB for
deck generation. One concern per module:

    model        frozen dataclasses — profiles, records, mappings
    ingest       csv/xlsx bytes → DataFrame + per-column profile
    repository   named saved datasets on disk (browser stores only the id)
"""
from __future__ import annotations

from studio.dataset.ingest import profile_frame, read_upload
from studio.dataset.model import ColumnProfile, DatasetProfile, DatasetRecord
from studio.dataset.repository import DatasetRepository, get_repository

__all__ = [
    "ColumnProfile",
    "DatasetProfile",
    "DatasetRecord",
    "DatasetRepository",
    "get_repository",
    "profile_frame",
    "read_upload",
]
