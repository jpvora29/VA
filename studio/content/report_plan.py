"""ReportPlan — the argument contract (DESIGN.md §10.1).

The second of the four contracts: storyline, selected claims, implications,
decisions and actions. It is *design-independent* — no geometry, no `Block`s. The
DeckSpec build step constructs visuals from `visual_ref` + `fact_ids` (the
semantic/visual seam, §10, "Move to build_deck").

This evolves the old `QBRContentSpec` (`studio/content/model.py`):

  - `Evidence` (embedded prose)  → numbers live in `EvidencePack`; findings carry
    `Claim`s that reference `fact_ids`.
  - `Finding.materiality: float` → `Importance` (four named factors, weighted SUM —
    never a product) **plus** an orthogonal `confidence` that gates *how* a finding
    shows, never *whether* (§10.4).
  - `Finding.visual: Block`       → `visual_ref` (a spec, not a `Block`).
  - header fields (audience, objective, report_type, …) added so the same data
    produces audience-appropriate decks via selection policy, one pipeline (§10.6).
  - prior-QBR `Commitment`s are first-class (§10.8).

Reuses `Action` and `DataGap` from `studio.content.model` rather than redefining
them. Pure data + the importance scorer (a pure function); no engine/LLM/Dash/pptx.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from studio.content.model import Action, DataGap

# ── allowed enums (kept as constants, not Enum, to match the repo's dict-dispatch idiom) ──

REPORT_TYPES = frozenset({"full_qbr", "exec_summary", "recap"})
AUDIENCES = frozenset(
    {"carrier_leadership", "marsh_regional", "country", "product", "internal", "external_carrier"}
)
#: Who a deck is for when nobody said. The carrier's own team: this is a product an
#: Insurer Consulting Group takes TO a carrier, so the client-facing read is the
#: default and the internal regional view is the deliberate choice.
DEFAULT_AUDIENCE = "carrier_leadership"
CLAIM_TYPES = frozenset({"observation", "driver", "interpretation", "recommendation", "decision"})
PLACEMENTS = frozenset({"main", "appendix", "gap"})

# Claim types that assert causation/explanation — only allowed when backed by a
# decomposition fact (§10.5). Content QA enforces this; declared here as the
# single source of truth.
EXPLANATORY_CLAIM_TYPES = frozenset({"driver", "interpretation"})

# Default importance weights; overridable from rules.yaml. Sum need not be 1 — the
# threshold is applied to the raw weighted sum.
DEFAULT_IMPORTANCE_WEIGHTS: Mapping[str, float] = {
    "financial_materiality": 0.40,
    "change_severity": 0.30,
    "strategic_relevance": 0.20,
    "actionability": 0.10,
}
DEFAULT_MAIN_DECK_THRESHOLD = 0.50


# ── claims ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Claim:
    """A typed, evidence-traceable statement — the unit of the argument.

    INVARIANT (enforced in content QA, §10.7): a claim whose `claim_type` is in
    `EXPLANATORY_CLAIM_TYPES` must carry ≥1 `fact_id` from a decomposition measure
    — no "why" without a decomposition; concentration/correlation is never phrased
    as causality.
    """

    text: str
    claim_type: str                              # see CLAIM_TYPES
    fact_ids: Sequence[str] = ()                 # EvidencePack ids — every number traceable
    confidence: str = "high"                     # high | medium | low


# ── materiality (importance ⟂ confidence, §10.4) ──────────────────────────────


@dataclass(frozen=True)
class Importance:
    """Four named factors (each 0..1). Scored by a weighted SUM, not a product, so
    one low factor cannot zero an otherwise critical finding."""

    financial_materiality: float = 0.0
    change_severity: float = 0.0
    strategic_relevance: float = 0.0
    actionability: float = 0.0


def score_importance(
    imp: Importance, weights: Mapping[str, float] = DEFAULT_IMPORTANCE_WEIGHTS
) -> float:
    """Weighted sum of the four factors — the selection score (pure, deterministic)."""
    return (
        imp.financial_materiality * weights["financial_materiality"]
        + imp.change_severity * weights["change_severity"]
        + imp.strategic_relevance * weights["strategic_relevance"]
        + imp.actionability * weights["actionability"]
    )


def decide_placement(
    imp: Importance,
    *,
    weights: Mapping[str, float] = DEFAULT_IMPORTANCE_WEIGHTS,
    threshold: float = DEFAULT_MAIN_DECK_THRESHOLD,
) -> str:
    """`main` if importance clears the threshold, else `appendix` (pure)."""
    return "main" if score_importance(imp, weights) >= threshold else "appendix"


# ── findings ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Finding:
    """A decision-oriented unit of the story → becomes one slide.

    `claims` flow observation → driver → interpretation → recommendation. Numbers
    are referenced (via each claim's `fact_ids`), never embedded. `visual_ref` is a
    *spec* the DeckSpec build step turns into a `Block`; this contract holds no
    `Block`.
    """

    section: str                                 # agenda section id (content.model.AGENDA)
    claims: Sequence[Claim]
    importance: Importance = field(default_factory=Importance)
    confidence: str = "medium"                   # ORTHOGONAL to importance — gates HOW it shows
    placement: str = "main"                      # main | appendix | gap
    visual_ref: Optional[Mapping[str, object]] = None   # e.g. {"kind": "chart", "chart": "bar", "fact_ids": [...]}
    owner: Optional[str] = None
    due_date: Optional[str] = None

    def claim(self, claim_type: str) -> Optional[Claim]:
        return next((c for c in self.claims if c.claim_type == claim_type), None)

    @property
    def action_title(self) -> str:
        """The takeaway sentence: the recommendation claim, else the observation."""
        c = self.claim("recommendation") or self.claim("observation")
        return c.text if c else ""


# ── prior-QBR continuity (§10.8) ──────────────────────────────────────────────


@dataclass(frozen=True)
class Commitment:
    """An action carried from a previous QBR — tracked, not re-derived."""

    title: str
    owner: str
    due_date: str
    status: str = "not_started"                  # not_started | in_progress | done | blocked
    expected_impact: str = ""
    actual_impact: str = ""
    delay_reason: str = ""
    carry_forward: str = ""                       # keep | drop | revise


# ── the plan ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReportPlan:
    """The argument for one (report_type, audience). Design-independent."""

    # header — who/why; drives selection policy (one pipeline, dict-dispatch, §10.6)
    report_type: str                             # see REPORT_TYPES
    audience: str                                # see AUDIENCES
    meeting_objective: str = ""
    decision_horizon: str = "next quarter"
    tone: str = "direct"
    confidentiality_policy: str = "no_peer_names"
    comparison_basis: str = "prior_year"         # prior_year | vs_plan | peer_aggregate
    # subject
    subject: str = "Market"
    country: Optional[str] = None
    period: str = ""
    comparison_period: str = ""
    # the argument
    thesis: str = ""
    what_changed: Sequence[str] = ()
    findings: Sequence[Finding] = ()
    decisions: Sequence[Claim] = ()              # decision-type claims
    actions: Sequence[Action] = ()               # reused from content.model (has .status)
    prior_commitments: Sequence[Commitment] = ()
    data_gaps: Sequence[DataGap] = ()            # projection of blocked capabilities (methodology slide)

    def main_findings(self) -> Sequence[Finding]:
        return tuple(f for f in self.findings if f.placement == "main")

    def appendix_findings(self) -> Sequence[Finding]:
        return tuple(f for f in self.findings if f.placement == "appendix")
