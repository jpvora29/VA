"""Structured diff between two golden traces (decisions doc #9).

Pure and credential-free — the unit-testable core of shadow mode. Separates
**behavior** signals (route, skills, entities, charts — these must NOT change
during a context-only refactor) from the **token** signal (which is the *goal*:
it should drop). `has_behavior_change` is what a shadow-parity test asserts is
False; `token_delta` is what a token-savings report reads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from tests.golden.harness import GoldenTrace


@dataclass
class TraceDiff:
    id: str
    route_changed: Optional[Tuple[str, str]] = None       # (baseline, candidate)
    depth_changed: Optional[Tuple[str, str]] = None
    skills_added: List[str] = field(default_factory=list)
    skills_removed: List[str] = field(default_factory=list)
    entities_changed: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)
    charts_changed: Optional[Tuple[list, list]] = None
    error_changed: Optional[Tuple[Optional[str], Optional[str]]] = None
    token_delta: int = 0
    token_pct: Optional[float] = None

    def has_behavior_change(self) -> bool:
        """True if any route/depth/skills/entities/charts/error differ.

        Token movement is deliberately excluded — cheaper prompts are the point,
        not a regression.
        """
        return bool(
            self.route_changed
            or self.depth_changed
            or self.skills_added
            or self.skills_removed
            or self.entities_changed
            or self.charts_changed
            or self.error_changed
        )

    def summary(self) -> str:
        parts: List[str] = []
        if self.route_changed:
            parts.append(f"route {self.route_changed[0]!r}->{self.route_changed[1]!r}")
        if self.depth_changed:
            parts.append(f"depth {self.depth_changed[0]!r}->{self.depth_changed[1]!r}")
        if self.skills_added:
            parts.append(f"+skills {self.skills_added}")
        if self.skills_removed:
            parts.append(f"-skills {self.skills_removed}")
        if self.entities_changed:
            parts.append(f"entities {self.entities_changed}")
        if self.charts_changed:
            parts.append("charts changed")
        if self.error_changed:
            parts.append(f"error {self.error_changed[0]!r}->{self.error_changed[1]!r}")
        tok = f"tokens {self.token_delta:+d}"
        if self.token_pct is not None:
            tok += f" ({self.token_pct:+.1f}%)"
        parts.append(tok)
        return f"[{self.id}] " + ("; ".join(parts) if parts else "no change")


def diff_traces(baseline: GoldenTrace, candidate: GoldenTrace) -> TraceDiff:
    d = TraceDiff(id=baseline.id)

    if baseline.route != candidate.route:
        d.route_changed = (baseline.route, candidate.route)
    if baseline.depth != candidate.depth:
        d.depth_changed = (baseline.depth, candidate.depth)

    base_skills, cand_skills = set(baseline.selected_skills), set(candidate.selected_skills)
    d.skills_added = sorted(cand_skills - base_skills)
    d.skills_removed = sorted(base_skills - cand_skills)

    keys = set(baseline.resolved_entities) | set(candidate.resolved_entities)
    for key in sorted(keys):
        b, c = baseline.resolved_entities.get(key), candidate.resolved_entities.get(key)
        if b != c:
            d.entities_changed[key] = (b, c)

    if baseline.chart_specs != candidate.chart_specs:
        d.charts_changed = (baseline.chart_specs, candidate.chart_specs)

    if baseline.error != candidate.error:
        d.error_changed = (baseline.error, candidate.error)

    d.token_delta = candidate.token_total - baseline.token_total
    if baseline.token_total:
        d.token_pct = 100.0 * d.token_delta / baseline.token_total

    return d


def diff_sets(
    baseline: List[GoldenTrace], candidate: List[GoldenTrace]
) -> List[TraceDiff]:
    """Diff two full runs, matched by trace id."""
    by_id = {t.id: t for t in candidate}
    diffs: List[TraceDiff] = []
    for base in baseline:
        cand = by_id.get(base.id)
        if cand is None:
            diffs.append(TraceDiff(id=base.id, error_changed=(base.error, "MISSING")))
            continue
        diffs.append(diff_traces(base, cand))
    return diffs
