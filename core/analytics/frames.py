"""``FrameSource`` — an in-memory table source the primitives accept in place of an engine.

The analytics primitives take an ``engine`` and push their aggregation down to SQLite.
An uploaded dataset has no warehouse behind it: its tables are DataFrames, and the
columns it happens to carry are whatever the user's spreadsheet had. Handing one of
these to a primitive routes it to the pandas twin in
:mod:`core.analytics.pandas_library` — same contract, same ``AnalyticsFact``s, no SQL.

The seam is deliberately one object rather than a flag: everything downstream already
threads ``engine`` from the selection to the primitive, so a source that quacks like an
engine reaches every primitive without touching a single caller.

Two rules the SQL path cannot follow, and the reason this exists:

  * a cut over a column the data does not have yields NO facts, rather than raising
    "no such column" and taking the whole page down with it;
  * a filter on a column the data does not have matches NO rows, because an ``AND``
    constraint that cannot be evaluated cannot be satisfied — silently widening the
    scope would answer a different question from the one that was asked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

import pandas as pd


@dataclass(frozen=True)
class FrameSource:
    """Named tables held as DataFrames — the in-memory twin of a SQLAlchemy engine.

    ``label`` identifies the source in logs and cache keys (a dataset id, say).
    """

    tables: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    label: str = "frames"

    def has(self, table: str) -> bool:
        return table in self.tables

    def table(self, name: str) -> pd.DataFrame:
        """``name``'s frame, or an EMPTY frame when the source has no such table.

        Empty rather than absent: a primitive over a missing table returns no facts,
        which is what a page needs to leave the section out — the same degradation an
        empty result set gives it.
        """
        frame = self.tables.get(name)
        return frame if frame is not None else pd.DataFrame()

    def columns(self, table: str) -> frozenset:
        return frozenset(str(c) for c in self.table(table).columns)


def as_frame_source(engine: Optional[Any]) -> Optional[FrameSource]:
    """``engine`` as a :class:`FrameSource`, or None when it is a real engine.

    The single dispatch test — used by the primitives and by nothing else.
    """
    return engine if isinstance(engine, FrameSource) else None


def frame_source(tables: Dict[str, pd.DataFrame], *, label: str = "frames") -> FrameSource:
    """Build a source from ``{table name: frame}`` (drops the empty/missing ones)."""
    return FrameSource(
        tables={name: frame for name, frame in tables.items() if frame is not None},
        label=label,
    )
