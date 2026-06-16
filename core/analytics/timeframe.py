"""Deterministic timeframe resolution — "compute the latest year, don't ask".

The planner is handed `valid_year_quarter` (ascending; last element is the most
recent period) but *choosing* the timeframe is left to the LLM, so "latest year"
queries intermittently aggregate across all years or pick the wrong period — the
reliability complaint Phase 1 targets.

This module makes the default deterministic. It does NOT invent semantics: it
enforces the already-always-on rule in `gpr-default-timeframe` /
`survey-default-timeframe` — *when the query names no time reference, default to
the latest available year (never an all-years aggregate)*. When the query DOES
carry a time reference (an explicit year/quarter, a multi-period term like YoY /
trend / across years, or a relative term like "last year"), this returns ""  and
leaves resolution to the planner + timeframe skills, exactly as today.

Pure and stdlib-only (no dspy / DB / API key) so it is unit-testable in isolation;
the planner wires it in behind a flag (default off = zero behaviour change).
"""
from __future__ import annotations

import os
import re
from typing import Iterable

# An explicit four-digit year ("... in 2023").
_EXPLICIT_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

# A quarter reference ("Q2", "quarter").
_QUARTER = re.compile(r"(?i)\bq[1-4]\b|\bquarter")

# Time references that must NOT collapse to a single latest year — either they
# span multiple periods (trend / YoY / across years) or they name a relative
# period the context filler resolves separately (last year). Their presence means
# "do not auto-default"; the planner + timeframe skills handle them.
_TIME_REFERENCE = re.compile(
    r"(?i)\b("
    r"yoy|y-o-y|year[\s-]*over[\s-]*year|"
    r"trend|growth|cagr|"
    r"over\s+time|across\s+years?|by\s+year|each\s+year|per\s+year|year[\s-]*on[\s-]*year|"
    r"historical|history|"
    r"rolling|ttm|trailing|"
    r"last\s+year|prior\s+year|previous\s+year|"
    r"last\s+\d+\s+years?|past\s+\d+\s+years?|"
    r"renewal"
    r")\b"
)


def _latest_year(valid_year_quarter: Iterable) -> str:
    """The maximum four-digit year across the valid periods, as a string.

    Works whether the entries are plain years (``2024``) or year-quarter strings
    (``"2025-Q1"``) — it extracts every embedded year and returns the max, so the
    default is a YEAR (matching `Year = MAX(Year)` in the timeframe skills), not a
    partial latest quarter.
    """
    years = [
        int(match)
        for entry in (valid_year_quarter or [])
        for match in re.findall(r"(?:19|20)\d{2}", str(entry))
    ]
    return str(max(years)) if years else ""


def resolve_default_timeframe(
    valid_year_quarter: Iterable, query: str, *, timeframe_hint: str = ""
) -> str:
    """Return the latest year to default to, or "" to defer to the planner.

    Returns "" (no auto-default) when ANY of these hold, so explicit / multi-period
    / relative timeframes are never overridden:
      - the context filler already resolved a relative term (`timeframe_hint` set);
      - the query names an explicit year or quarter;
      - the query carries a multi-period or relative time term.
    Otherwise returns the latest available year (e.g. "2025").
    """
    if timeframe_hint and timeframe_hint.strip():
        return ""
    text = query or ""
    if _EXPLICIT_YEAR.search(text) or _QUARTER.search(text) or _TIME_REFERENCE.search(text):
        return ""
    return _latest_year(valid_year_quarter)


def timeframe_resolution_enabled() -> bool:
    """True when the planner should deterministically fill an empty timeframe.

    ANALYTICS_TIMEFRAME_RESOLUTION = off (default) | shadow | on. Default off =
    zero behaviour change; flip to `on` (with a live run + the golden harness)
    before relying on it. Mirrors `core.context.gate.gate_enabled`.
    """
    return os.getenv("ANALYTICS_TIMEFRAME_RESOLUTION", "off").lower() in {"on", "shadow"}
