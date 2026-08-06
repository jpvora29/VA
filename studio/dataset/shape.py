"""Reshape a dataset and keep its metadata true to the new shape.

Adding, deriving or deleting a column changes what the dataset HAS, so three things
must move together or the Data tab starts lying: the shape recipe (``transforms``),
the column profile the mapping form is drawn from, and the mappings themselves — a
deleted column cannot keep a mapping, and a new one deserves a proposal.

This module owns that one job. Each entry point takes the repository (injected, so
every path is testable without a Dash app), applies exactly one change, and returns
the updated record with everything back in agreement.

The profile always describes the WORKING frame — the raw upload with the recipe
replayed — which is what makes a derived column mappable like any other.
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Tuple

from logger import get_logger
from studio.dataset.automap import propose_mappings
from studio.dataset.ingest import profile_frame
from studio.dataset.materialize import working_frame
from studio.dataset.model import ColumnMapping, DatasetProfile, DatasetRecord, TransformOp
from studio.dataset.transform import RECIPES, apply_transforms

logger = get_logger(__name__)


# ── mapping reconciliation ───────────────────────────────────────────────────


def reconcile_mappings(profile: DatasetProfile,
                       existing: Tuple[ColumnMapping, ...]) -> Tuple[ColumnMapping, ...]:
    """Mappings for exactly the columns in ``profile``, in its order.

    A column the user already decided on keeps that decision untouched; one that has
    vanished takes its mapping with it; a new one gets a proposal that cannot claim a
    canonical target an existing mapping already holds.
    """
    kept = {m.uploaded: m for m in existing}
    columns = [c for c in profile.columns if c.name in kept]
    fresh = DatasetProfile(
        n_rows=profile.n_rows,
        n_cols=profile.n_cols,
        columns=tuple(c for c in profile.columns if c.name not in kept),
    )
    taken = {kept[c.name].target for c in columns if kept[c.name].target}
    proposed = {m.uploaded: m for m in propose_mappings(fresh, taken=taken)}
    return tuple(
        kept.get(column.name) or proposed.get(column.name) or ColumnMapping(uploaded=column.name)
        for column in profile.columns
    )


def resync(repo, record: Optional[DatasetRecord]) -> Optional[DatasetRecord]:
    """Re-profile ``record`` from its working frame and reconcile its mappings.

    Idempotent, and the single place the record is brought back into agreement with
    its data — called after every shape change, on upload, and when a dataset saved
    before auto-mapping existed is re-opened.
    """
    if record is None:
        return None
    try:
        frame = working_frame(repo, record)
    except ValueError as exc:
        logger.warning("resync skipped for %s: %s", record.dataset_id, exc)
        return record
    profile = profile_frame(frame)
    mappings = reconcile_mappings(profile, record.mappings)
    if profile == record.profile and mappings == record.mappings:
        return record
    updated = replace(record, profile=profile, mappings=mappings,
                      n_rows=profile.n_rows, n_cols=profile.n_cols)
    repo.update_record(updated)
    return updated


# ── the shape operations ─────────────────────────────────────────────────────


def _append(repo, record: DatasetRecord, op: TransformOp) -> DatasetRecord:
    """Validate ``op`` against the current frame, persist it, and resync."""
    frame = working_frame(repo, record)
    apply_transforms(frame, [op])                       # raises before anything is saved
    updated = replace(record, transforms=(*record.transforms, op))
    repo.update_record(updated)
    return resync(repo, updated)


def _free_name(name: str, record: DatasetRecord, frame_columns) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Give the new column a name.")
    if name in set(frame_columns):
        raise ValueError(f"There is already a column called {name!r}.")
    return name


def add_computed(repo, record: DatasetRecord, name: str, formula: str) -> DatasetRecord:
    """A new column from an arithmetic formula over the existing ones."""
    frame = working_frame(repo, record)
    op = TransformOp(kind="add", name=_free_name(name, record, frame.columns),
                     formula=str(formula or ""))
    return _append(repo, record, op)


def add_derived(repo, record: DatasetRecord, name: str, source: str, recipe: str) -> DatasetRecord:
    """A new column read out of ``source`` by a named recipe (Year from a date…)."""
    frame = working_frame(repo, record)
    if recipe not in RECIPES:
        raise ValueError("Pick what to read from that column.")
    op = TransformOp(kind="derive", name=_free_name(name, record, frame.columns),
                     source=str(source or ""), recipe=recipe)
    return _append(repo, record, op)


def suggested_name(source: str, recipe: str) -> str:
    """The name a derived column defaults to — ``Billing Date`` + ``year`` → ``Year``."""
    stem = {"year": "Year", "quarter": "Quarter", "month": "Month",
            "month_name": "Month_Name", "date": "Date"}.get(recipe)
    if stem:
        return stem
    return f"{source}_{recipe}".strip("_")


def drop_column(repo, record: DatasetRecord, name: str) -> DatasetRecord:
    """Delete any column — mapped or not.

    A mapped column loses its mapping with it (``resync``), which is the honest
    outcome: the deck cannot bind to data that is no longer there. Nothing is lost
    permanently — the raw upload is untouched and the drop is one recipe step.
    """
    op = TransformOp(kind="drop", name=str(name))
    return _append(repo, record, op)


def undo_last(repo, record: DatasetRecord) -> DatasetRecord:
    """Remove the most recent shape step (the way back from a wrong delete)."""
    if not record.transforms:
        return record
    updated = replace(record, transforms=record.transforms[:-1])
    repo.update_record(updated)
    return resync(repo, updated)


def shape_history(record: DatasetRecord) -> List[str]:
    """The recipe as readable lines, newest last — what the Data tab shows."""
    labels = []
    for op in record.transforms:
        if op.kind == "drop":
            labels.append(f"Deleted {op.name}")
        elif op.kind == "derive":
            labels.append(f"{op.name} = {RECIPES.get(op.recipe, (op.recipe,))[0]} of {op.source}")
        else:
            labels.append(f"{op.name} = {op.formula}")
    return labels


def derived_columns(record: DatasetRecord) -> set:
    """Names of columns this recipe created — the tab marks them as not-from-the-file."""
    dropped = {op.name for op in record.transforms if op.kind == "drop"}
    made = {op.name for op in record.transforms if op.kind in ("add", "derive")}
    return made - dropped
