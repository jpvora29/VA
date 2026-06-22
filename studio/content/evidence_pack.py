"""EvidencePack — the validated-data contract (DESIGN.md §10.1).

The first of the four contracts: pure facts, comparisons, provenance and — via the
Phase-0 capability probe (§10.3) — an honest record of *what the data can and
cannot support*. No narrative, no geometry.

Two invariants this layer exists to enforce:

  1. **Every number has a stable `fact_id`.** Claims in the `ReportPlan` reference
     numbers by id rather than restating them, and the renderers pull the `rendered`
     display string verbatim — the LLM never emits a number (DESIGN.md §2, §10.5).
  2. **Determinism** (§10.11): the same compute output always yields the same
     `fact_id`s, so `EvidencePack` → `ReportPlan` → `DeckSpec` selection is
     byte-stable. `make_fact_id` is therefore a pure function of (measure, dims,
     period) only.

`studio/content/evidence.py` (being evolved) builds an `EvidencePack` from an
`OverallResult` + a capability probe; `studio/content/report_plan.py` consumes it.
This module is pure data + pure helpers (no engine, no LLM, no Dash, no pptx).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


# ── stable identity ───────────────────────────────────────────────────────────


def make_fact_id(measure: str, dims: Mapping[str, Any], period: Optional[int] = None) -> str:
    """Deterministic id for a number.

    Pure function of its inputs (no clock, no counter) so identical compute output
    always produces identical ids — the determinism contract (§10.11). Dims are
    canonicalised by sorting so key order never changes the id.
    """
    canon = "|".join(
        [measure, repr(period)] + [f"{k}={v}" for k, v in sorted(dims.items(), key=lambda kv: str(kv[0]))]
    )
    return "f_" + hashlib.blake2s(canon.encode("utf-8"), digest_size=8).hexdigest()


# ── provenance & facts ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Provenance:
    """Where a number came from — the chain back to the ledger."""

    flow: str                                    # "gpr" | "survey"
    source: str                                  # human label, e.g. "GPR — premium ledger"
    primitive: str = ""                          # compute fn that produced it
    filters: Mapping[str, Any] = field(default_factory=dict)
    period: Optional[int] = None


@dataclass(frozen=True)
class EvidenceItem:
    """One validated number. Claims reference this by `fact_id`."""

    fact_id: str
    measure: str                                 # premium_total | premium_movement | rank | sow | hhi | peer_ratio …
    value: float
    rendered: str                                # display string (money()/pct()) — renderer uses verbatim
    dims: Mapping[str, Any] = field(default_factory=dict)   # {Product_Line: "Property", year: 2025}
    confidence: str = "high"                     # high | medium | low | modeled
    provenance: Optional[Provenance] = None
    derived_from: Sequence[str] = ()             # fact_ids this was computed from (movement = current − prior)


# ── capability probe (Phase 0) ────────────────────────────────────────────────


@dataclass(frozen=True)
class Capability:
    """What the live data can support for one agenda section (§10.3).

    Produced by a probe that runs against the dataset each generation — never a
    hand-authored table. A blocked capability becomes a `DataGap` on the
    methodology slide, never generic filler.
    """

    section: str                                 # agenda section id (see content.model.AGENDA)
    data_available: bool
    comparison_available: bool
    confidence: str = "high"                     # high | medium | low
    reason: str = ""                             # populated only when blocked


# ── the pack ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EvidencePack:
    """Validated facts + capability map for one subject/period. No narrative."""

    subject: str
    country: Optional[str]
    period: str
    comparison_period: str
    items: Mapping[str, EvidenceItem] = field(default_factory=dict)        # fact_id -> item
    capabilities: Mapping[str, Capability] = field(default_factory=dict)   # section_id -> capability
    sources: Sequence[str] = ()

    def get(self, fact_id: str) -> Optional[EvidenceItem]:
        return self.items.get(fact_id)

    def rendered(self, fact_id: str) -> str:
        """The display string the renderer must use verbatim ('' if unknown)."""
        item = self.items.get(fact_id)
        return item.rendered if item else ""

    def supports(self, section: str) -> bool:
        cap = self.capabilities.get(section)
        return bool(cap and cap.data_available)

    def gaps(self) -> Sequence[Capability]:
        """Blocked sections, in agenda order of insertion — the methodology slide source."""
        return tuple(c for c in self.capabilities.values() if not c.data_available)
