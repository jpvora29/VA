"""One verification gate for every written answer, whatever route produced it.

`verify_answer` used to run only inside the analyst subgraph, so a lookup,
survey or hybrid answer — most of what users ask — got the figure check and
nothing else. This is the shared step both now call: run the checks, apply the
one deterministic repair (removing an unhedged causal claim), and turn every
other failure into a limitation the reader sees.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.answers.verification import (
    UNSUPPORTED_CAUSATION,
    Verdict,
    VerificationInput,
    limitations_for,
    strip_unsupported_causation,
    verdict,
    verify_answer,
)
from core.observability import log_event
from logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class GateResult:
    """The answer after the gate. `record` is None when nothing changed."""

    text: str
    record: Optional[dict]
    verdict: Verdict


def run_verify_gate(data: VerificationInput, record: dict, *, node: str, route: str = "") -> GateResult:
    """Verify one answer; repair or annotate its record when a check fails."""
    result = verify_answer(data)
    if result.passed:
        return GateResult(data.text, None, result)
    repaired, removed = strip_unsupported_causation(data.text, result.failures)
    remaining = verdict(f for f in result.failures if f.kind != UNSUPPORTED_CAUSATION)
    limitations = tuple(dict.fromkeys(
        (*(record.get("limitations") or ()), *limitations_for(remaining))
    ))
    text = repaired or data.text
    updated = dict(record, content=text, limitations=list(limitations),
                   verification=result.as_dicts())
    log_event(logger, "answer_verified", logging.WARNING, node=node, route=route,
              stage=result.stage, failures=[f.kind for f in result.failures],
              causal_sentences_removed=removed, limitations=len(limitations))
    return GateResult(text, updated, result)
