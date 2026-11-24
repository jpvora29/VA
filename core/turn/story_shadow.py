"""Shadow measurement: does the evidence a turn gathers cover its story?

Called from the analyst planner (what the plan's steps will reach) and the
analyst verifier (what the evidence actually satisfied). It logs one
`story_coverage` event and changes nothing. Same switch as the TurnSpec shadow:
`TURN_SPEC=off` silences it. It never raises — a measurement must not fail a turn.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from core.analysis.requirements import EvidenceContract
from core.analysis.story import build_story_plan, sections_left_open
from core.observability import log_event
from core.turn.node import turn_spec_mode
from logger import get_logger

logger = get_logger(__name__)


def record_story_coverage(
    shape: str,
    contract: EvidenceContract,
    reached: Iterable[str],
    *,
    stage: str,
    node: str,
    route: str = "",
) -> None:
    """Log which story sections `reached` leaves open, and which cannot fill at all."""
    if turn_spec_mode() == "off" or contract is None:
        return
    try:
        story = build_story_plan(shape, contract)
        left_open = sections_left_open(story, reached)
    except Exception as exc:  # noqa: BLE001 - shadow measurement only
        log_event(
            logger, "story_coverage_error", logging.WARNING, node=node, error=str(exc)
        )
        return
    unfillable = story.unfillable()
    log_event(
        logger,
        "story_coverage",
        logging.WARNING if unfillable or left_open else logging.INFO,
        node=node,
        stage=stage,
        route=route,
        shape=story.shape,
        intent=contract.intent,
        sections=[s.key for s in story.sections],
        unfillable={s.key: s.status for s in unfillable},
        left_open=list(left_open),
    )
