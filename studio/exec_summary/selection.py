"""Bounded selection — what enters a model call (design Section 19).

Every industry is computed; at most six unique ones (top 3 premium leaders, bottom 3
low-participation slices) go into one product payload. The labels describe explicit
ranking views, not verdicts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from studio.exec_summary.cube import UNMAPPED
from studio.exec_summary.metrics import SliceMetrics

TOP = "top"
BOTTOM = "bottom"


@dataclass(frozen=True)
class IndustrySelection:
    rule_version: str
    rows: Tuple[SliceMetrics, ...]            # unique, at most top_n + bottom_n
    labels: Dict[str, Tuple[str, ...]]        # industry → ("top",) / ("bottom",) / both
    top: Tuple[str, ...]
    bottom: Tuple[str, ...]
    total: int
    eligible: int

    @property
    def omitted(self) -> int:
        return self.total - len(self.rows)


def _valid(rows: Sequence[SliceMetrics]) -> List[SliceMetrics]:
    return [r for r in rows if r.scope.industry not in (None, UNMAPPED)]


def top_industries(rows: Sequence[SliceMetrics], n: int) -> List[SliceMetrics]:
    """Carrier premium ↓, then carrier SoW ↓, then industry id — premium leaders."""
    leaders = [r for r in _valid(rows) if r.carrier_cur > 0]
    leaders.sort(key=lambda r: (-r.carrier_cur, -(r.sow_cur or 0.0), r.scope.industry))
    return leaders[:n]


def bottom_industries(rows: Sequence[SliceMetrics], n: int,
                      material_marsh: float) -> List[SliceMetrics]:
    """Carrier SoW ↑ among material Marsh books (zero activity included), then Marsh
    growth ↓, Marsh premium ↓, industry id — low-participation slices."""
    material = [r for r in _valid(rows) if r.marsh_cur >= material_marsh and r.sow_cur is not None]
    material.sort(key=lambda r: (r.sow_cur, -(r.marsh_growth.pct or 0.0), -r.marsh_cur,
                                 r.scope.industry))
    return material[:n]


def select_industries(rows: Sequence[SliceMetrics], *, top_n: int, bottom_n: int,
                      material_marsh: float, rule_version: str) -> IndustrySelection:
    top = top_industries(rows, top_n)
    bottom = bottom_industries(rows, bottom_n, material_marsh)
    labels: Dict[str, Tuple[str, ...]] = {}
    unique: List[SliceMetrics] = []
    for view, picked in ((TOP, top), (BOTTOM, bottom)):
        for r in picked:
            name = r.scope.industry
            if name not in labels:
                unique.append(r)
                labels[name] = ()
            labels[name] = labels[name] + (view,)
    return IndustrySelection(
        rule_version=rule_version, rows=tuple(unique), labels=labels,
        top=tuple(r.scope.industry for r in top), bottom=tuple(r.scope.industry for r in bottom),
        total=len(rows), eligible=len(_valid(rows)),
    )


def leading_and_weak(items: Sequence, n: int, *, strength_key, weakness_key,
                     is_weak) -> Tuple[list, list]:
    """Up to ``n`` leaders and ``n`` weak items, distinct, by numeric keys (not by prose)."""
    leaders = sorted(items, key=strength_key)[:n]
    weak = [i for i in sorted(items, key=weakness_key) if is_weak(i) and i not in leaders][:n]
    return leaders, weak
