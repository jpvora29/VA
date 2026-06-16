"""Rows → `FactFrame`: deterministic column-role detection.

Primitives stay flow-agnostic by asking for columns by *role* instead of by
hardcoded name. This module owns the role patterns and the `build_frame` step
that tags each column in a result set with the role(s) it matches.

The patterns are the canonical home for what
``core/agents/boardroom.py``'s `_*_COLS` regexes do today (extended to cover the
survey perception dimensions — section / attribute / segment). Phase 0 introduces
this as a standalone seam with **zero** changes to the live boardroom path; a
later phase can point boardroom at these.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from core.analytics.types import FactFrame

# role -> matcher. A column may carry several roles (e.g. nothing here is
# mutually exclusive); each role scans independently, mirroring the boardroom
# signal detector.
ROLE_PATTERNS: Mapping[str, "re.Pattern[str]"] = {
    "temporal": re.compile(r"(?i)year|quarter|month|period|date"),
    "geo": re.compile(r"(?i)country|market|region"),
    "product": re.compile(r"(?i)product|line|cover|practice|lob|section|attribute|segment"),
    "carrier": re.compile(r"(?i)carrier|peer|group"),
    "premium": re.compile(r"(?i)premium|sow|wallet|appetite|gpr"),
    "perception": re.compile(r"(?i)score|nps|perception|rating"),
}


def detect_roles(columns: Iterable[str]) -> Dict[str, Tuple[str, ...]]:
    """Map each role to the columns (in input order) that match its pattern."""
    cols = list(columns)
    roles: Dict[str, Tuple[str, ...]] = {}
    for role, pattern in ROLE_PATTERNS.items():
        matched = tuple(c for c in cols if pattern.search(str(c)))
        if matched:
            roles[role] = matched
    return roles


def _columns(rows: List[Dict[str, Any]]) -> List[str]:
    """Union of keys across rows, preserving first-seen order."""
    seen: Dict[str, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key, None)
    return list(seen)


def build_frame(rows: Iterable[Any]) -> FactFrame:
    """Normalize result rows into a `FactFrame` with detected column roles.

    Non-dict rows are wrapped as ``{"value": row}`` so a scalar result set still
    forms a valid frame. Role detection runs over the union of columns.
    """
    normalized: Tuple[Dict[str, Any], ...] = tuple(
        row if isinstance(row, dict) else {"value": row} for row in rows
    )
    roles = detect_roles(_columns(list(normalized)))
    return FactFrame(rows=normalized, roles=roles)
