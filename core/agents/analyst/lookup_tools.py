"""Primitives first: answer a lookup step from the analytics library.

Adapter over `AnalyticsToolRunner` (the same runner the old GPR and survey
rails call) that returns analyst evidence instead of graph-state keys. An empty
list means the library did not cover the question, and the caller falls back to
the solver, which can write SQL. All or nothing, as on the old rails: a
half-covered question is not answered from the library.

The rows are peer-redacted here, at the same boundary every other tool path
uses, because this path bypasses the solver's own redaction.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from core.agents.analyst.answer_table import select_answer_evidence
from core.agents.common.analytics_tools import (
    AnalyticsToolRunner,
    AnalyticsTurn,
    analytics_tools_enabled,
)
from core.agents.common.peer_privacy import redactor_for
from core.agents.common.peers import pinned_peers
from core.analytics.tools.rows import public_facts_digest
from core.observability import log_event
from logger import get_logger

logger = get_logger(__name__)

#: The `tool` an evidence record carries when the library computed it.
LIBRARY_TOOL = "analytics_library"


def lookup_primitive_evidence(
    *,
    question: str,
    flow: str,
    lens: str,
    resolved_filters: Mapping[str, Any],
    custom_peers: dict | None = None,
    custom_peers_active: bool = False,
    runner: AnalyticsToolRunner | None = None,
    engine: Any = None,
) -> list[dict[str, Any]]:
    """The library's answer as raw evidence records, or [] when it has none."""
    if not analytics_tools_enabled():
        return []
    runner = runner or AnalyticsToolRunner()
    if not runner.enabled:
        return []
    try:
        turn = runner.run(
            flow=flow,
            user_query=question,
            resolved_filters=resolved_filters,
            peers=pinned_peers(custom_peers, flow, active=custom_peers_active),
            engine=engine,
        )
    except Exception as exc:  # noqa: BLE001 - the solver is the fallback, not an error page
        log_event(
            logger,
            "lookup_primitives_failed",
            logging.WARNING,
            node="analyst_lookup",
            flow=flow,
            error=str(exc),
        )
        return []
    log_lookup_turn(turn, flow)
    if not turn.covered:
        return []
    return [evidence_from_turn(turn, flow, lens, resolved_filters, custom_peers)]


def evidence_from_turn(
    turn: AnalyticsTurn,
    flow: str,
    lens: str,
    resolved_filters: Mapping[str, Any],
    custom_peers: dict | None,
) -> dict[str, Any]:
    """One raw evidence record, shaped like the solver's `compute_metric` output."""
    redactor = redactor_for(flow, dict(resolved_filters), custom_peers)
    return {
        "flow": flow,
        "sql": turn.provenance(),
        "rows": redactor.rows(turn.rows),
        "lens": lens,
        "tool": LIBRARY_TOOL,
        "parameters": {"calls": [call.describe() for call in turn.calls]},
        "scope": dict(turn.scope),
        "actual_scope": dict(turn.scope),
        "facts": public_facts_digest(turn.facts, redactor),
        "defaulted_year": turn.defaulted_year,
    }


def answer_analytics(
    evidence: Sequence[Mapping[str, Any]],
    flow: str,
    *,
    primary_lens: str = "",
) -> dict[str, Any] | None:
    """The old rails' `*_analytics` record for this flow's answer table, or None.

    The evidence panel formats a table's columns from this record's fact digest
    ("$1.77M", not "1770.0"). Only library evidence has one. None is written
    rather than nothing, because graph state is checkpointed per conversation and
    an earlier turn's digest would otherwise format this turn's table.
    """
    best = select_answer_evidence(evidence, flow, primary_lens=primary_lens)
    if not best or best.get("tool") != LIBRARY_TOOL:
        return None
    return {
        "calls": list((best.get("parameters") or {}).get("calls") or []),
        "scope": dict(best.get("scope") or {}),
        "facts": list(best.get("facts") or []),
    }


def log_lookup_turn(turn: AnalyticsTurn, flow: str) -> None:
    log_event(
        logger,
        "lookup_primitives",
        node="analyst_lookup",
        flow=flow,
        covered=turn.covered,
        calls=[call.describe() for call in turn.calls],
        rejected=list(turn.rejected),
        skipped=list(turn.skipped),
        rows=len(turn.rows),
    )
