"""The Data tab's review queue: which mapping rows need the author, and why.

The mapping used to be one long list in upload order, so the three rows that needed a
decision sat among nine that were already right. The queue splits them:

* **Needs your decision** — a proposal the matcher was not sure of, an unmapped column
  with nothing to explain it, and a date column when the deck still has no Year;
* **Suggested mappings** — confident proposals, confirmed rows and described columns.

Each row says in words why it maps where it does (the matcher's own evidence) and how
sure that is, and the readiness rail says which of the three columns every deck needs
are in place — and, for a missing Year, which date column it can be made from.

Pure: a :class:`~studio.dataset.model.DatasetRecord` in, plain dataclasses out.
"""
from __future__ import annotations

import string
from dataclasses import dataclass
from typing import List, Optional, Tuple

from studio.dataset.automap import is_proposed
from studio.dataset.model import (
    REQUIRED_TARGETS,
    ColumnMapping,
    ColumnProfile,
    DatasetRecord,
    premium_mapped,
)

HIGH, MEDIUM, LOW = "High", "Medium", "Low"
HIGH_FLOOR, MEDIUM_FLOOR = 0.85, 0.6


def _label(target: str) -> str:
    return target.replace("_", " ")


def column_letter(index: int) -> str:
    """Spreadsheet-style column letter for a 0-based index: 0 -> A, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = string.ascii_uppercase[rem] + letters
    return letters


def is_date_like(profile: ColumnProfile) -> bool:
    """A date column — or a text column whose sample values all read as dates.

    Ingest only types ISO dates as dates, so "27 Nov 2024" arrives as text; it is still the
    column a Year can be made from (the Year recipe parses it the same way).
    """
    if profile.kind == "date":
        return True
    if profile.kind != "text" or not profile.sample:
        return False
    import warnings

    import pandas as pd

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(pd.Series(list(profile.sample)), errors="coerce")
    return bool(parsed.notna().all()) and not all(str(v).strip().isdigit() for v in profile.sample)


def confidence_tier(mapping: Optional[ColumnMapping]) -> str:
    """High / Medium / Low for a mapped row; "" for an unmapped one. A row the author
    confirmed is as sure as it gets."""
    if mapping is None or not mapping.target:
        return ""
    if not is_proposed(mapping):
        return HIGH
    if mapping.confidence >= HIGH_FLOOR:
        return HIGH
    return MEDIUM if mapping.confidence >= MEDIUM_FLOOR else LOW


def reason(profile: ColumnProfile, mapping: Optional[ColumnMapping]) -> str:
    """Why this row maps where it does, in the matcher's own terms."""
    target = mapping.target if mapping else ""
    if not target:
        if is_date_like(profile):
            return "Dates — make the deck's Year from it"
        return "No standard match — describe it, or pick a target"
    source = mapping.source
    if source == "user":
        return "You confirmed this"
    if source == "values":
        return f"Values look like {_label(target)}"
    if source == "fuzzy":
        return f"Name is close to {_label(target)}"
    if source == "ai":
        return f"Suggested as {_label(target)}"
    return f"Name matches {_label(target)}"


@dataclass(frozen=True)
class QueueRow:
    profile: ColumnProfile
    mapping: Optional[ColumnMapping]
    letter: str
    tier: str
    reason: str
    needs_decision: bool
    can_derive_year: bool = False   # an unmapped date while the deck has no Year


def _needs_decision(profile: ColumnProfile, mapping: Optional[ColumnMapping],
                    description: str, year_missing: bool) -> bool:
    target = mapping.target if mapping else ""
    if not target:
        if year_missing and is_date_like(profile):
            return True
        return not description.strip()
    return is_proposed(mapping) and mapping.confidence < HIGH_FLOOR


def queue(record: DatasetRecord, description_of) -> Tuple[List[QueueRow], List[QueueRow]]:
    """``(needs your decision, suggested mappings)``, each in upload order.

    ``description_of(profile, mapping)`` is the row's current description (the page owns
    how a blank one is seeded), so "unmapped and undescribed" is judged the way the
    submit check judges it.
    """
    covered = {m.target for m in record.mappings if m.target}
    year_missing = "Year" not in covered
    by_col = {m.uploaded: m for m in record.mappings}
    decide, suggested = [], []
    for index, profile in enumerate(record.profile.columns):
        mapping = by_col.get(profile.name)
        row = QueueRow(
            profile=profile, mapping=mapping, letter=column_letter(index),
            tier=confidence_tier(mapping), reason=reason(profile, mapping),
            needs_decision=_needs_decision(profile, mapping,
                                           description_of(profile, mapping), year_missing),
            can_derive_year=bool(year_missing and not (mapping and mapping.target)
                                 and is_date_like(profile)),
        )
        (decide if row.needs_decision else suggested).append(row)
    return decide, suggested


@dataclass(frozen=True)
class Readiness:
    """One of the three columns every deck needs, and where it stands."""

    target: str
    ready: bool
    detail: str
    derive_from: str = ""          # a date column a missing Year can be created from


def readiness(record: DatasetRecord) -> List[Readiness]:
    by_target = {m.target: m.uploaded for m in record.mappings if m.target}
    dates = [p.name for p in record.profile.columns
             if is_date_like(p) and p.name not in by_target.values()]
    out = []
    for target in REQUIRED_TARGETS:
        if target in by_target:
            out.append(Readiness(target, True, f"Mapped from {by_target[target]}"))
        elif target == "Premium" and premium_mapped(record):
            name = record.primary.name if record.primary else "your primary measure"
            out.append(Readiness(target, True, f"Calculated as {name}"))
        elif target == "Year" and dates:
            out.append(Readiness(target, False, f"Create it from {dates[0]}",
                                 derive_from=dates[0]))
        elif target == "Premium":
            out.append(Readiness(target, False, "Map a money column, or define one below"))
        else:
            out.append(Readiness(target, False, f"Map the column that holds {_label(target)}"))
    return out
