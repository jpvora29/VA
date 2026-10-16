"""Running the four LLM stages (design Section 18).

    product + opportunity (concurrent, bounded)  ->  country (concurrent)  ->  overall

One call per scope, each with a bounded payload and a typed answer. A stage answer goes
through the verifier; an answer with rejected findings gets ONE retry carrying the exact
reasons; if it still cannot support the stage's minimum, the deterministic fallback
answers instead. Nothing unverified leaves this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

from logger import get_logger
from studio.exec_summary import fallback as FB
from studio.exec_summary import payloads as P
from studio.exec_summary.analysis import ExecAnalysis
from studio.exec_summary.evidence import EvidenceStore
from studio.exec_summary.llm import StageModel, cache_key, cached, store
from studio.exec_summary.prompts import repair_prompt, system_prompt, user_prompt
from studio.exec_summary.schemas import (
    SOURCE_FALLBACK,
    SOURCE_MODEL,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PARTIAL,
    StageOutput,
    StageResult,
)
from studio.exec_summary.verify import VerifiedStage, verify_stage
from studio.parallel import gather_list

logger = get_logger(__name__)


@dataclass(frozen=True)
class StageEnv:
    """What every stage call needs besides its own payload."""

    model: StageModel
    store: EvidenceStore
    run_id: str
    rule_version: str
    budgets: object               # config.Budgets — per-stage input budget
    concurrency: int
    forbidden_names: FrozenSet[str] = frozenset()
    universe: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class StageCall:
    payload: P.StagePayload
    fallback: Callable[[], StageOutput]


@dataclass
class CommentaryResult:
    children: Dict[str, StageResult] = field(default_factory=dict)   # product + opportunity
    countries: Dict[str, StageResult] = field(default_factory=dict)
    overall: Optional[StageResult] = None

    def all_results(self) -> List[StageResult]:
        return [*self.children.values(), *self.countries.values(),
                *([self.overall] if self.overall else [])]


# ── one stage ────────────────────────────────────────────────────────────────


def _verify(output: Optional[StageOutput], call: StageCall, env: StageEnv) -> Optional[VerifiedStage]:
    if output is None:
        return None
    return verify_stage(output, call.payload, env.store, forbidden_names=env.forbidden_names,
                        universe=env.universe, finding_prefix=f"{call.payload.stage[0]}")


def _ask(call: StageCall, env: StageEnv, system: str, user: str) -> Optional[StageOutput]:
    key = cache_key(env.model.label, env.rule_version, system, user)
    hit = cached(key)
    if hit is not None:
        return hit
    return env.model.complete(call.payload.stage, system, user)


def _good_enough(v: Optional[VerifiedStage], call: StageCall) -> bool:
    return v is not None and v.scope_ok and len(v.findings) >= call.payload.min_findings


def _envelope(call: StageCall, env: StageEnv, v: VerifiedStage, source: str,
              errors: Tuple[str, ...]) -> StageResult:
    status = (STATUS_COMPLETE if not v.errors and len(v.findings) >= call.payload.min_findings
              else STATUS_PARTIAL if v.findings else STATUS_FAILED)
    return StageResult(
        run_id=env.run_id, stage=call.payload.stage, scope_id=call.payload.scope_id,
        status=status, source=source, findings=v.findings,
        coverage={"evidence_ids_offered": len(call.payload.allowed_ids)},
        child_result_refs=call.payload.child_refs, errors=errors)


def run_stage(call: StageCall, env: StageEnv) -> StageResult:
    """Model answer → verify → one targeted retry → deterministic fallback."""
    system = system_prompt(call.payload.stage, max_findings=call.payload.max_findings,
                           min_findings=call.payload.min_findings)
    errors: List[str] = []
    fitted = P.trim_for_budget(call.payload, system, env.budgets.input_for(call.payload.stage))
    if fitted is None:
        errors.append("payload over the input token budget")
    else:
        user = user_prompt(fitted.to_json())
        first = _ask(call, env, system, user)
        v1 = _verify(first, call, env)
        if v1 is not None and not v1.errors and _good_enough(v1, call):
            store(cache_key(env.model.label, env.rule_version, system, user), first)
            return _envelope(call, env, v1, SOURCE_MODEL, ())
        if v1 is not None:
            errors.extend(v1.errors)
            retry = env.model.complete(call.payload.stage, system,
                                       repair_prompt(fitted.to_json(), list(v1.errors)))
            v2 = _verify(retry, call, env)
            best = max((v for v in (v1, v2) if _good_enough(v, call)),
                       key=lambda v: len(v.findings), default=None)
            if best is not None:
                if v2 is not None:
                    errors.extend(f"retry: {e}" for e in v2.errors)
                return _envelope(call, env, best, SOURCE_MODEL, tuple(errors))
        else:
            errors.append(f"model unavailable ({env.model.label})")
    fb = _verify(call.fallback(), call, env)
    if fb.errors:
        logger.warning("exec_summary fallback for %s dropped findings: %s",
                       call.payload.scope_id, fb.errors)
    return _envelope(call, env, fb, SOURCE_FALLBACK, tuple(errors) + fb.errors)


def _run_all(calls: List[StageCall], env: StageEnv) -> List[StageResult]:
    """Independent calls concurrently, results in input order (deterministic output)."""
    return gather_list([partial(run_stage, c, env) for c in calls], workers=env.concurrency)


# ── the four stage types, in dependency order ────────────────────────────────


def run_child_stages(analysis: ExecAnalysis, env: StageEnv) -> Dict[str, StageResult]:
    """Product and opportunity calls — both use deterministic product status, so neither
    waits on the other's prose."""
    calls: List[StageCall] = []
    for ca in analysis.countries:
        for pa in ca.products:
            calls.append(StageCall(P.product_payload(analysis, ca, pa),
                                   partial(FB.product_fallback, analysis, ca, pa)))
            opp = P.opportunity_payload(analysis, ca, pa)
            if opp is not None:
                calls.append(StageCall(opp, partial(FB.opportunity_fallback, analysis, ca, pa)))
    return {r.scope_id: r for r in _run_all(calls, env)}


def run_country_stages(analysis: ExecAnalysis, children: Dict[str, StageResult],
                       env: StageEnv) -> Dict[str, StageResult]:
    calls = [StageCall(P.country_payload(analysis, ca, children),
                       partial(FB.country_fallback, analysis, ca, children))
             for ca in analysis.countries]
    return {r.scope_id: r for r in _run_all(calls, env)}


def run_overall_stage(analysis: ExecAnalysis, countries: Dict[str, StageResult],
                      children: Dict[str, StageResult], env: StageEnv) -> StageResult:
    call = StageCall(P.overall_payload(analysis, countries, children),
                     partial(FB.overall_fallback, analysis, countries))
    return run_stage(call, env)


def write_commentary(analysis: ExecAnalysis, env: StageEnv) -> CommentaryResult:
    """All four stages; the overall result is what the summary slide shows."""
    children = run_child_stages(analysis, env)
    countries = run_country_stages(analysis, children, env)
    overall = run_overall_stage(analysis, countries, children, env)
    return CommentaryResult(children=children, countries=countries, overall=overall)
