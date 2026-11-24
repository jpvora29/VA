"""The shadow graph node: build the TurnSpec, log it, change nothing.

Sits between the HITL gates and the router, so it sees the final filters and
directives the router acts on. `TURN_SPEC=off` removes even the logging;
any other value (default `shadow`) builds and records. It never raises — a
measurement must not fail a turn.
"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from typing import Any

from core.analysis.story import build_story_plan
from core.observability import log_event
from core.turn.build import build_turn_spec, spec_contract
from core.turn.disagreements import find_disagreements
from logger import get_logger

logger = get_logger(__name__)


def turn_spec_mode() -> str:
    return os.getenv("TURN_SPEC", "shadow").strip().lower()


def turn_spec_node(state: dict[str, Any]) -> dict[str, Any]:
    """Record this turn's single interpretation and its internal contradictions."""
    if turn_spec_mode() == "off":
        return {"turn_spec": None}
    try:
        messages = state.get("messages") or []
        question = messages[-1].content if messages else ""
        spec = build_turn_spec(question, state.get("routing_context"))
        disagreements = find_disagreements(spec)
        spec = replace(spec, disagreements=tuple(d.as_dict() for d in disagreements))
        story = build_story_plan(spec.shape, spec_contract(spec))
    except Exception as exc:  # noqa: BLE001 - shadow measurement only
        log_event(
            logger, "turn_spec_error", logging.WARNING, node="turn_spec", error=str(exc)
        )
        return {"turn_spec": None}
    log_event(
        logger,
        "turn_spec_built",
        logging.WARNING if disagreements else logging.INFO,
        node="turn_spec",
        family=spec.family,
        depth=spec.depth,
        operation=spec.operation,
        shape=spec.shape,
        presentation=spec.presentation,
        requirements=list(spec.requirements),
        period_named=spec.period_named,
        disagreements=[d.rule for d in disagreements],
        story_unfillable={s.key: s.status for s in story.unfillable()},
    )
    return {"turn_spec": spec.as_dict()}
