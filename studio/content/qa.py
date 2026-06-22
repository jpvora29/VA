"""Content QA — the gate that runs BEFORE any rendering (DESIGN.md §10.7).

Deterministic, pure checks over a `ReportPlan` + its `EvidencePack`. This is the
content tier of the two-tier QA model; visual QA (overflow, fonts, alignment) runs
later, after a `RenderPlan` exists.

The checks are a registry of pure callables (the repo's dispatch idiom) so adding a
rule is one entry, not a new branch. Each returns `Violation`s; `check_report_plan`
runs them all. Nothing here touches the engine, an LLM, Dash or pptx — it is fully
unit-testable in isolation.

Invariants enforced (the load-bearing ones from §10.5):
  - every `fact_id` a claim cites must exist in the `EvidencePack`;
  - an explanatory claim (`driver`/`interpretation`) must cite ≥1 *decomposition*
    fact — no "why" without a decomposition; concentration/correlation may be
    *observed* but never asserted as causation in a bare observation claim;
  - confidentiality: with `no_peer_names`, no banned peer name may appear in prose.

Recommendation/decision claims may be judgment-based (§10.5), so they are NOT
required to cite facts — but any fact they *do* cite must still exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, List, Sequence, Tuple

from studio.content.evidence_pack import EvidencePack
from studio.content.report_plan import (
    EXPLANATORY_CLAIM_TYPES,
    Claim,
    ReportPlan,
)

# Measures that constitute a quantitative decomposition — they can support a "why".
DECOMPOSITION_MEASURES = frozenset(
    {"premium_movement", "movement_by_dim", "concentration", "hhi", "rate_volume_mix"}
)

# Causal phrasing that must not appear in a bare `observation` claim (heuristic —
# emitted as a warning, not an error).
CAUSAL_MARKERS: Tuple[str, ...] = (
    "because", "caused by", "due to", "drove", "led to",
    "as a result of", "thanks to", "owing to", "driven by",
)

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Violation:
    code: str
    severity: str            # ERROR | WARNING
    message: str
    location: str            # e.g. "finding[premium_movement].claim[driver]"


# ── claim iteration ────────────────────────────────────────────────────────────


def _all_claims(plan: ReportPlan) -> Iterator[Tuple[str, Claim]]:
    """Yield (location, claim) for every claim in the plan — findings then decisions."""
    for f in plan.findings:
        for c in f.claims:
            yield f"finding[{f.section}].claim[{c.claim_type}]", c
    for c in plan.decisions:
        yield f"decision.claim[{c.claim_type}]", c


# ── individual checks (pure) ───────────────────────────────────────────────────


def check_claim_facts_exist(plan: ReportPlan, pack: EvidencePack) -> List[Violation]:
    """Every cited `fact_id` must resolve in the EvidencePack."""
    out: List[Violation] = []
    for loc, claim in _all_claims(plan):
        for fid in claim.fact_ids:
            if pack.get(fid) is None:
                out.append(Violation("fact_missing", ERROR, f"cites unknown fact_id {fid!r}", loc))
    return out


def check_explanatory_decomposition(plan: ReportPlan, pack: EvidencePack) -> List[Violation]:
    """`driver`/`interpretation` claims need ≥1 decomposition fact — no "why" without one."""
    out: List[Violation] = []
    for loc, claim in _all_claims(plan):
        if claim.claim_type not in EXPLANATORY_CLAIM_TYPES:
            continue
        measures = {pack.get(fid).measure for fid in claim.fact_ids if pack.get(fid)}
        if not (measures & DECOMPOSITION_MEASURES):
            out.append(Violation(
                "unsupported_causation", ERROR,
                f"{claim.claim_type} claim has no decomposition fact (has {sorted(measures) or 'none'})",
                loc,
            ))
    return out


def check_causal_language(plan: ReportPlan, pack: EvidencePack) -> List[Violation]:
    """Heuristic: an `observation` claim should state what, not why (warning)."""
    out: List[Violation] = []
    for loc, claim in _all_claims(plan):
        if claim.claim_type != "observation":
            continue
        low = claim.text.lower()
        hit = next((m for m in CAUSAL_MARKERS if m in low), None)
        if hit:
            out.append(Violation(
                "causal_language_in_observation", WARNING,
                f"observation uses causal phrasing {hit!r} — make it a driver claim with a decomposition fact",
                loc,
            ))
    return out


def check_confidentiality(plan: ReportPlan, pack: EvidencePack) -> List[Violation]:
    """Under `no_peer_names`, no banned peer name may appear in claim prose.

    Banned names are read from `pack`'s nothing-by-default; callers pass them via
    `check_report_plan(..., banned_names=...)`. With no list this is a no-op (it
    cannot invent names to check) — the wiring step must supply the peer roster.
    """
    return []  # name list is supplied at call-time; see check_report_plan


def _check_confidentiality_with_names(
    plan: ReportPlan, banned_names: Sequence[str]
) -> List[Violation]:
    out: List[Violation] = []
    if plan.confidentiality_policy != "no_peer_names" or not banned_names:
        return out
    lowered = [(n, n.lower()) for n in banned_names if n]
    for loc, claim in _all_claims(plan):
        low = claim.text.lower()
        for name, name_low in lowered:
            if name_low in low:
                out.append(Violation("peer_name_leak", ERROR, f"individual peer name {name!r} in prose", loc))
    return out


# ── registry + entrypoint ───────────────────────────────────────────────────────

# Order is presentation order only; each check is independent.
CHECKS: Tuple[Callable[[ReportPlan, EvidencePack], List[Violation]], ...] = (
    check_claim_facts_exist,
    check_explanatory_decomposition,
    check_causal_language,
    check_confidentiality,
)


def check_report_plan(
    plan: ReportPlan, pack: EvidencePack, *, banned_names: Sequence[str] = ()
) -> List[Violation]:
    """Run every content check; return all violations (empty == passes the gate)."""
    out: List[Violation] = []
    for check in CHECKS:
        out.extend(check(plan, pack))
    out.extend(_check_confidentiality_with_names(plan, banned_names))
    return out


def has_errors(violations: Sequence[Violation]) -> bool:
    return any(v.severity == ERROR for v in violations)
