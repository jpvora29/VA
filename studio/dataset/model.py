"""Frozen data contracts for uploaded datasets.

These move between ingest, the repository, the mapping step and the Data-tab
UI. Values live in the repository's SQLite files; these classes carry only
metadata, so they serialize cleanly into the browser store and callback state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Tuple

# Broad column kinds derived from pandas dtypes — enough for the mapping step
# to rank candidates (a "number" column can map to Premium; a "text" one cannot).
COLUMN_KINDS = ("number", "text", "date")

# The canonical targets the fixed QBR templates cannot fill without: a measure,
# the subject carrier, and the reporting period. A mapping only reaches the
# "mapped" status once all three are covered.
REQUIRED_TARGETS = ("Premium", "Carrier_Group", "Year")


@dataclass(frozen=True)
class ColumnProfile:
    """What we learned about one uploaded column (no data, just shape)."""

    name: str
    kind: str                       # number | text | date
    null_pct: float
    n_distinct: int
    sample: Tuple[str, ...] = ()    # up to a handful of distinct example values


@dataclass(frozen=True)
class DatasetProfile:
    """Shape summary of a whole upload, shown on the Data tab."""

    n_rows: int
    n_cols: int
    columns: Tuple[ColumnProfile, ...] = ()


@dataclass(frozen=True)
class CustomMeasure:
    """A KPI the user declared for an uploaded numeric column (or a formula).

    Captured when a metric column doesn't match a canonical measure: the user
    names it, says how to aggregate and format it, and optionally supplies the
    calculation. Custom KPIs feed pivots and slide widgets — they never replace
    the template-bound Premium analytics.
    """

    name: str
    column: str = ""                # uploaded column ("" when formula-based)
    formula: str = ""               # arithmetic over uploaded columns
    aggregation: str = "sum"        # sum | avg
    format: str = "number"          # currency | percent | number
    description: str = ""


@dataclass(frozen=True)
class TransformOp:
    """One replayable column operation on the working frame.

    ``add`` computes a column from an arithmetic formula; ``derive`` reads one out of
    another column with a named recipe (a Year out of a billing date); ``drop`` removes
    one. Stored as a recipe rather than a materialized column so the shape survives a
    re-upload and stays auditable.
    """

    kind: str                       # add | derive | drop
    name: str
    formula: str = ""               # for add: arithmetic over existing columns
    source: str = ""                # for derive: the column it is read from
    recipe: str = ""                # for derive: which reading (see transform.RECIPES)


@dataclass(frozen=True)
class PivotSpec:
    """A pivot over the working frame. ``filters`` is also the deck's row-level
    slice when the dataset is submitted — the pivot shapes scope, the deck still
    computes from row-level data."""

    rows: Tuple[str, ...] = ()
    cols: str = ""
    values: str = ""
    aggregation: str = "sum"        # sum | avg | count
    filters: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()

    @property
    def is_runnable(self) -> bool:
        return bool(self.rows and self.values)


@dataclass(frozen=True)
class ColumnMapping:
    """One uploaded column → one canonical GPR column (HITL-editable).

    ``description`` starts as the flow registry's definition for the target and
    stays editable — the user's wording is persisted with the dataset.
    ``source`` records who proposed it: deterministic rule, AI rescue, or user.
    """

    uploaded: str
    target: str = ""                # canonical column name, "" = unmapped
    description: str = ""
    confidence: float = 0.0
    source: str = "unmapped"        # alias | fuzzy | values | ai | user | unmapped


@dataclass(frozen=True)
class DatasetRecord:
    """The saved-dataset metadata the repository lists and the browser references."""

    dataset_id: str
    name: str
    filename: str
    created: str                    # ISO timestamp
    n_rows: int
    n_cols: int
    status: str = "uploaded"        # uploaded | mapped | submitted
    mappings: Tuple[ColumnMapping, ...] = ()
    profile: DatasetProfile = field(default_factory=lambda: DatasetProfile(0, 0))
    # The designated primary money measure when no column maps to Premium
    # directly (its result materializes AS Premium; the name is kept for labels).
    primary: Optional[CustomMeasure] = None
    # KPIs declared for unmatched metric columns — pivots + widgets only.
    custom_measures: Tuple[CustomMeasure, ...] = ()
    # Replayable shape recipe (add/drop columns) applied before materialization.
    transforms: Tuple[TransformOp, ...] = ()
    # The current pivot; its filters double as the deck's row-level slice.
    pivot: Optional[PivotSpec] = None

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


def mapping_complete(mappings: Tuple[ColumnMapping, ...]) -> bool:
    """True when every required canonical target has an uploaded column mapped."""
    covered = {m.target for m in mappings if m.target}
    return all(t in covered for t in REQUIRED_TARGETS)


def undescribed_unmapped(mappings: Tuple[ColumnMapping, ...]) -> Tuple[str, ...]:
    """Unmapped columns that carry no description, in form order.

    A column with no canonical target has nothing to explain it — the deck
    can't infer meaning from the name alone — so a description is mandatory
    before the mapping can be submitted."""
    return tuple(
        m.uploaded for m in mappings
        if not m.target and not (m.description or "").strip()
    )


def premium_mapped(record: "DatasetRecord") -> bool:
    """True when a money measure exists: a column mapped to Premium, or a
    designated primary measure that materializes as Premium. Deck generation
    is refused without one — every template analytic is premium-derived."""
    if any(m.target == "Premium" for m in record.mappings):
        return True
    return bool(record.primary and (record.primary.column or record.primary.formula))


def record_complete(record: "DatasetRecord") -> bool:
    """Like ``mapping_complete``, but a designated primary measure covers Premium."""
    covered = {m.target for m in record.mappings if m.target}
    if premium_mapped(record):
        covered.add("Premium")
    return all(t in covered for t in REQUIRED_TARGETS)


def replace_mappings(
    record: DatasetRecord,
    mappings: Tuple[ColumnMapping, ...],
    *,
    status: Optional[str] = None,
) -> DatasetRecord:
    """A copy of ``record`` with new mappings (and optionally a new status)."""
    return replace(record, mappings=mappings, status=status or record.status)


def _measure_from_json(raw: Optional[Mapping[str, Any]]) -> Optional[CustomMeasure]:
    if not raw:
        return None
    return CustomMeasure(
        name=raw.get("name", ""),
        column=raw.get("column", ""),
        formula=raw.get("formula", ""),
        aggregation=raw.get("aggregation", "sum"),
        format=raw.get("format", "number"),
        description=raw.get("description", ""),
    )


def _pivot_from_json(raw: Optional[Mapping[str, Any]]) -> Optional[PivotSpec]:
    if not raw:
        return None
    return PivotSpec(
        rows=tuple(raw.get("rows", ())),
        cols=raw.get("cols", ""),
        values=raw.get("values", ""),
        aggregation=raw.get("aggregation", "sum"),
        filters=tuple((str(c), tuple(v)) for c, v in raw.get("filters", ())),
    )


def record_from_json(raw: Mapping[str, Any]) -> DatasetRecord:
    """Rebuild a ``DatasetRecord`` from its ``to_json`` form (repository disk files)."""
    profile_raw = raw.get("profile") or {}
    columns = tuple(
        ColumnProfile(
            name=c["name"],
            kind=c.get("kind", "text"),
            null_pct=float(c.get("null_pct", 0.0)),
            n_distinct=int(c.get("n_distinct", 0)),
            sample=tuple(c.get("sample", ())),
        )
        for c in profile_raw.get("columns", ())
    )
    return DatasetRecord(
        dataset_id=raw["dataset_id"],
        name=raw.get("name", raw["dataset_id"]),
        filename=raw.get("filename", ""),
        created=raw.get("created", ""),
        n_rows=int(raw.get("n_rows", 0)),
        n_cols=int(raw.get("n_cols", 0)),
        status=raw.get("status", "uploaded"),
        mappings=tuple(
            ColumnMapping(
                uploaded=m["uploaded"],
                target=m.get("target", ""),
                description=m.get("description", ""),
                confidence=float(m.get("confidence", 0.0)),
                source=m.get("source", "unmapped"),
            )
            for m in raw.get("mappings", ())
        ),
        profile=DatasetProfile(
            n_rows=int(profile_raw.get("n_rows", 0)),
            n_cols=int(profile_raw.get("n_cols", 0)),
            columns=columns,
        ),
        primary=_measure_from_json(raw.get("primary")),
        custom_measures=tuple(
            m for m in (_measure_from_json(x) for x in raw.get("custom_measures", ())) if m
        ),
        transforms=tuple(
            TransformOp(
                kind=t["kind"], name=t["name"], formula=t.get("formula", ""),
                source=t.get("source", ""), recipe=t.get("recipe", ""),
            )
            for t in raw.get("transforms", ())
        ),
        pivot=_pivot_from_json(raw.get("pivot")),
    )
