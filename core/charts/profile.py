"""What the result set IS, decided deterministically before any model sees it.

The chart agent's enums, the chart types it is offered, and the compact data
description in its prompt all come from here — one read of the DataFrame,
classified by the role vocabulary `ChartSpecCritic` already owns
(`temporal / measure_amount / measure_rate / dimension / identifier / constant`).

Reusing the critic's `classify_columns` is the point: the thing that PREVENTS a
bad spec and the thing that REPAIRS one must agree about what a column is, or the
critic will spend its time undoing the agent's legitimate choices.

Pure: pandas in, a frozen dataclass out. No LLM, no DB.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

import pandas as pd

from core.charts.critic import ColumnRole, classify_columns

# Distinct values sampled per dimension for the prompt. Enough for the model to
# recognise what a column holds; short enough that a 500-row result does not
# become a 500-line prompt.
_SAMPLE_VALUES = 5


@dataclass(frozen=True)
class ColumnProfile:
    """The chartable shape of one result set."""

    roles: Mapping[str, ColumnRole]
    row_count: int

    def _named(self, *kinds: str) -> List[str]:
        return [role.name for role in self.roles.values() if role.kind in kinds]

    @property
    def temporal(self) -> List[str]:
        return self._named("temporal")

    @property
    def dimensions(self) -> List[str]:
        return self._named("dimension")

    @property
    def amounts(self) -> List[str]:
        return self._named("measure_amount")

    @property
    def rates(self) -> List[str]:
        return self._named("measure_rate")

    @property
    def measures(self) -> List[str]:
        return self._named("measure_amount", "measure_rate")

    @property
    def chartable(self) -> bool:
        """False when there is nothing to draw — the `chart_type='none'` case.

        A single scalar, a single row, or a result with no measure has no chart in
        it. Saying so here means the agent is never asked to invent one.
        """
        return self.row_count >= 2 and bool(self.measures) and bool(
            self.dimensions or self.temporal or len(self.measures) >= 2
        )

    def cardinality(self, column: str) -> int:
        role = self.roles.get(column)
        return role.cardinality if role else 0

    def describe(self, samples: Mapping[str, Sequence[Any]]) -> str:
        """A compact, model-readable description of the columns and their roles.

        Deliberately not the raw rows: the agent decides which column goes on
        which axis, and for that it needs each column's ROLE and how many
        distinct values it has — not sixty rows of numbers it will only pattern
        match against.
        """
        lines = [f"{self.row_count} rows."]
        for role in self.roles.values():
            line = f"- {role.name} ({role.kind}, {role.cardinality} distinct)"
            values = samples.get(role.name) or ()
            if values:
                shown = ", ".join(str(v) for v in values)
                line += f": {shown}"
            lines.append(line)
        return "\n".join(lines)


def build_profile(df: pd.DataFrame) -> ColumnProfile:
    """Classify every column of `df` into the shared role vocabulary."""
    if df is None or df.empty:
        return ColumnProfile(roles={}, row_count=0)
    return ColumnProfile(roles=classify_columns(df), row_count=int(len(df)))


def sample_values(df: pd.DataFrame, profile: ColumnProfile) -> Dict[str, List[Any]]:
    """A few distinct values per non-measure column, for the prompt description.

    Measures are omitted on purpose — knowing that `Premium` holds 1_240_991.4 does
    not help decide which axis it belongs on, and it is the one place a model is
    tempted to read a number and repeat it as fact.
    """
    if df is None or df.empty:
        return {}
    samples: Dict[str, List[Any]] = {}
    for name, role in profile.roles.items():
        if role.is_measure or name not in df.columns:
            continue
        values = df[name].dropna().unique()[:_SAMPLE_VALUES]
        samples[name] = [v.item() if hasattr(v, "item") else v for v in values]
    return samples


def to_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Rows (the shape every caller has) as a DataFrame, or empty on junk."""
    try:
        frame = pd.DataFrame(list(rows or []))
    except Exception:  # noqa: BLE001 - a malformed result must not crash charting
        return pd.DataFrame()
    return frame
