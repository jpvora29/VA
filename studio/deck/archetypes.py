"""Dense slide archetypes — region templates that guarantee a *full* QBR slide.

A content slide is composed into a fixed set of regions so it never renders as a
half-empty "commentary rail | one chart" frame:

    ┌──────────────────────────────────────────┐
    │ STAT BAND (KPIs / evidence numbers)        │   ← top, full width
    ├───────────────┬────────────────────────────┤
    │ COMMENTARY    │ PRIMARY VISUAL             │   ← main row, fills height
    │ RAIL          │                            │
    ├───────────────┴────────────────────────────┤
    │ SECONDARY VISUAL (when a 2nd block exists) │   ← full-width row
    ├──────────────────────────────────────────┤
    │ RECOMMENDATION STRIP                       │   ← bottom (when present)
    └──────────────────────────────────────────┘

The composer (`studio/deck/compose.py`) picks an archetype deterministically from
what a slide actually carries; the Layout agent may later override the choice, but
only with an id from this catalog — so the result is always a valid, full slide.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Archetype:
    """A region template. ``secondary`` says where a 2nd visual goes."""

    name: str
    has_stat_band: bool
    has_secondary: bool


# The catalog both the deterministic composer and the Layout agent choose from.
ARCHETYPES = {
    "stat_dual": Archetype("stat_dual", has_stat_band=True, has_secondary=True),
    "stat_single": Archetype("stat_single", has_stat_band=True, has_secondary=False),
    "rail_dual": Archetype("rail_dual", has_stat_band=False, has_secondary=True),
    "rail_single": Archetype("rail_single", has_stat_band=False, has_secondary=False),
}
ARCHETYPE_IDS = tuple(ARCHETYPES)
