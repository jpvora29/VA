"""Deterministic slide composer — semantic SlideSpec → a full, dense LayoutPlan.

Classifies a content slide's blocks into the archetype regions (stat band ▸
commentary rail ▸ primary visual ▸ secondary visual ▸ recommendation) so the
renderers always fill the frame. When a slide has no explicit KPI band, a small
stat band is synthesised from its evidence numbers (already deterministic, already
fact-checked) so the top of the slide is never empty.

Pure data: no Dash, no python-pptx — both renderers consume the `LayoutPlan`. The
Layout agent (`studio/ai/layout_agent.py`) may override `archetype`, but only with
an id from `studio.deck.archetypes`, and the renderers tolerate any region being
empty, so a bad/blank AI choice degrades to a still-valid slide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from studio.deck.archetypes import ARCHETYPES
from studio.deck.model import SlideSpec

_MAX_STATS = 4


@dataclass(frozen=True)
class LayoutPlan:
    archetype: str
    stat_band: Tuple[Mapping[str, Any], ...] = ()    # KPI items for the top strip
    stat_from_evidence: bool = False                 # → don't also show evidence chips
    rail: Tuple[Mapping[str, Any], ...] = ()         # commentary takeaways
    primary: Optional[Any] = None                    # main visual Block
    secondary: Optional[Any] = None                  # full-width 2nd visual Block
    evidence: Tuple[Mapping[str, Any], ...] = ()
    reco: bool = False


def _stats_from_evidence(evidence: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """A compact stat band from a finding's evidence (label/value/detail rows)."""
    out: List[Mapping[str, Any]] = []
    for e in list(evidence)[:_MAX_STATS]:
        label = str(e.get("label", "") or "").strip().rstrip(".")
        value = str(e.get("value", "") or "").strip()
        if label and value:
            out.append({"label": label, "value": value, "delta": str(e.get("detail", "") or "")})
    return out


def compose(slide: SlideSpec) -> LayoutPlan:
    """Pick the densest valid archetype for ``slide`` and assign its regions."""
    blocks = list(slide.blocks)
    kpi = next((b for b in blocks if b.kind == "kpis"), None)
    visuals = [b for b in blocks if b.kind != "kpis"]

    stat_from_evidence = kpi is None
    stat = list(kpi.items) if kpi else _stats_from_evidence(slide.evidence)
    primary = visuals[0] if visuals else None
    secondary = visuals[1] if len(visuals) > 1 else None

    has_stat = bool(stat)
    has_secondary = secondary is not None
    archetype = (
        "stat_dual" if (has_stat and has_secondary)
        else "stat_single" if has_stat
        else "rail_dual" if has_secondary
        else "rail_single"
    )
    plan = LayoutPlan(
        archetype=archetype,
        stat_band=tuple(stat[:_MAX_STATS]),
        stat_from_evidence=stat_from_evidence,
        rail=tuple(slide.takeaways),
        primary=primary,
        secondary=secondary,
        evidence=tuple(slide.evidence),
        reco=bool(slide.recommendation),
    )
    # Honour a Layout-agent archetype hint (validated; a bad hint is ignored).
    hint = (slide.meta or {}).get("archetype")
    return apply_archetype(plan, hint) if hint else plan


def apply_archetype(plan: LayoutPlan, archetype: str) -> LayoutPlan:
    """Re-key a plan to a (validated) archetype id — the Layout agent's only lever.

    An unknown id, or one that needs a region the slide lacks, is ignored so the
    deterministic composition always stands.
    """
    arche = ARCHETYPES.get(archetype)
    if arche is None:
        return plan
    if arche.has_secondary and plan.secondary is None:
        return plan
    if arche.has_stat_band and not plan.stat_band:
        return plan
    from dataclasses import replace

    return replace(plan, archetype=archetype)
