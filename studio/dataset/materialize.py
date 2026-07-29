"""Materialize a mapped dataset into its canonical ``GPR`` table.

The submitted dataset's SQLite gains the table the analytics primitives query:
uploaded columns renamed to their canonical targets, the designated primary
measure computed AS ``Premium`` when nothing mapped to it directly, custom KPI
columns carried alongside, and the pivot's filters applied as the row-level
slice. An empty ``Peers`` table is created too, so peer analyses return no
rows instead of erroring (peers stay governed by design).
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from logger import get_logger
from studio.dataset.model import CustomMeasure, DatasetRecord, record_complete
from studio.dataset.pivot import slice_frame
from studio.dataset.repository import MAPPED_TABLE, DatasetRepository
from studio.dataset.transform import apply_transforms, safe_eval

logger = get_logger(__name__)

_NUMERIC_TARGETS = {"Premium", "Year"}


def working_frame(repo: DatasetRepository, record: DatasetRecord) -> pd.DataFrame:
    """The raw upload with the shape recipe (add/drop columns) replayed."""
    frame = repo.load_frame(record.dataset_id)
    if frame is None:
        raise ValueError("The dataset's data file is missing — re-upload it.")
    return apply_transforms(frame, record.transforms)


def _measure_series(frame: pd.DataFrame, measure: CustomMeasure) -> pd.Series:
    if measure.formula:
        return safe_eval(frame, measure.formula)
    if measure.column and measure.column in frame.columns:
        return pd.to_numeric(frame[measure.column], errors="coerce")
    raise ValueError(f"KPI {measure.name!r}: column {measure.column!r} not in the dataset.")


def materialized_frame(record: DatasetRecord, frame: pd.DataFrame) -> pd.DataFrame:
    """The canonical frame: mapped columns renamed, primary + custom KPIs computed,
    pivot slice applied. Pure — takes the working frame, returns the GPR frame."""
    sliced = slice_frame(frame, record.pivot) if record.pivot else frame
    out = pd.DataFrame(index=sliced.index)
    for m in record.mappings:
        if m.target and m.uploaded in sliced.columns:
            out[m.target] = sliced[m.uploaded]
    if "Premium" not in out.columns and record.primary:
        out["Premium"] = _measure_series(sliced, record.primary)
    for km in record.custom_measures:
        if km.name and km.name not in out.columns:
            out[km.name] = _measure_series(sliced, km)
    for col in _NUMERIC_TARGETS & set(out.columns):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "Year" in out.columns:
        out["Year"] = out["Year"].astype("Int64")
    return out.reset_index(drop=True)


def pivot_frame(record: DatasetRecord, frame: pd.DataFrame) -> pd.DataFrame:
    """The working frame enriched with declared KPI columns, for the pivot builder.

    Formula-based KPIs (and the primary measure) don't exist as uploaded
    columns; appending them here lets a pivot aggregate them like any other."""
    out = frame.copy()
    measures = list(record.custom_measures)
    if record.primary and record.primary.name:
        measures.append(record.primary)
    for m in measures:
        if m.name and m.name not in out.columns:
            try:
                out[m.name] = _measure_series(frame, m)
            except ValueError as exc:
                logger.warning("pivot KPI %s skipped: %s", m.name, exc)
    return out


def _ensure_empty_peers(engine) -> None:
    """A schema-only Peers table: peer queries run and return nothing."""
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE IF NOT EXISTS "Peers" '
            '("Carrier_Group" TEXT, "Overall_Peer_Group" TEXT)'
        ))


def materialize(repo: DatasetRepository, record: DatasetRecord) -> int:
    """Write the canonical table into the dataset's SQLite. Returns the row count.

    Raises ``ValueError`` (with a user-facing reason) when the mapping is not
    complete or a formula fails — the caller shows it on the Data page.
    """
    if not record_complete(record):
        raise ValueError(
            "Mapping incomplete — Premium (or a designated primary measure), "
            "Carrier Group and Year are required."
        )
    frame = working_frame(repo, record)
    gpr = materialized_frame(record, frame)
    engine = repo.engine(record.dataset_id)
    gpr.to_sql(MAPPED_TABLE, engine, if_exists="replace", index=False)
    _ensure_empty_peers(engine)
    # ASCII only: × and → break logging on cp1252 Windows consoles.
    logger.info(
        "dataset %s materialized: %s rows x %s cols -> %s",
        record.dataset_id, len(gpr), len(gpr.columns), MAPPED_TABLE,
    )
    return len(gpr)
