"""Typed contracts at the model boundary (design Sections 17, 18, 20).

Two layers, deliberately separate:

* :class:`StageOutput` / :class:`ModelFinding` — what the model is ASKED to return. Pydantic,
  ``extra="forbid"``, enums as ``Literal``, every field required (OpenAI strict JSON-schema
  mode needs that, and it is what keeps a small model from inventing keys). Array caps
  are enforced by the verifier rather than the schema, because strict mode rejects some
  JSON-schema constraints and a schema the endpoint refuses is worse than a cap we check.
* :class:`StageResult` / :class:`Finding` — the application's envelope AFTER verification:
  ``validation_status`` is set here, never by the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Tuple

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "1.0"

STAGE_PRODUCT = "product"
STAGE_OPPORTUNITY = "opportunity"
STAGE_COUNTRY = "country"
STAGE_OVERALL = "overall"

Severity = Literal["strength", "attention", "opportunity", "context"]


class ModelFinding(BaseModel):
    """One finding as the model writes it."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: Severity
    statement: str
    interpretation: str
    recommendation: str
    evidence_ids: List[str]
    qualifications: List[str]


class StageOutput(BaseModel):
    """The whole response of one stage call."""

    model_config = ConfigDict(extra="forbid")

    scope_id: str
    findings: List[ModelFinding]
    priority_refs: List[str]
    missing_references: List[str]


# ── after verification ───────────────────────────────────────────────────────

VERIFIED = "verified"
REJECTED = "rejected"

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"

SOURCE_MODEL = "model"
SOURCE_FALLBACK = "deterministic_fallback"
SOURCE_EMPTY = "empty"


@dataclass(frozen=True)
class Finding:
    finding_id: str
    rule_id: str
    scope_id: str
    severity: str
    statement: str
    interpretation: str
    recommendation: str
    evidence_ids: Tuple[str, ...]
    qualifications: Tuple[str, ...] = ()
    validation_status: str = VERIFIED


@dataclass(frozen=True)
class StageResult:
    """The common envelope every stage returns (design Section 17, StageResult)."""

    run_id: str
    stage: str
    scope_id: str
    status: str
    source: str
    findings: Tuple[Finding, ...] = ()
    priority_refs: Tuple[str, ...] = ()
    coverage: dict = field(default_factory=dict)
    child_result_refs: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)
