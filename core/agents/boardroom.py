"""Boardroom digest node.

Terminal enrichment step that runs after the route's insight writer (and the
follow-up node) when Boardroom Mode is active for the turn. It reshapes the
answer the rails already produced into a structured `BoardroomDigest` that the
UI renders as an inline dashboard card.

It is a strict no-op when `boardroom_mode` is False, so it can sit on the single
terminal edge of the main graph without affecting normal turns.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import dspy

from core.initialization import Initialization
from core.observability import log_event
from core.schemas.boardroom import BoardroomSignature
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)

# Cap rows handed to the LLM so a wide result set can't blow the context window;
# the digest only needs a representative sample to format KPIs from.
_MAX_DIGEST_ROWS = 60


class BoardroomDigestModule(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(BoardroomSignature)

    def forward(
        self, user_query: str, route: str, commentary: str, sql_output: Any
    ):
        with dspy.context(lm=Initialization.dspy_creative):
            result = self.predictor(
                user_query=user_query,
                route=route,
                commentary=commentary,
                sql_output=sql_output,
            )
        return result.digest


# Stateless module — instantiate once and reuse across turns.
_BOARDROOM_MODULE = BoardroomDigestModule()


def _gather_commentary(state: AgentState) -> str:
    """Collect EVERY answer text the turn produced, labelled by lens.

    Feeding all lenses (premium + survey + combined + gimmi) — not just the first —
    gives the digest model the cross-signal context the advanced widgets need
    (e.g. premium AND broker perception for the peer-positioning matrix)."""
    parts = []
    for label, key in (
        ("Combined", "combined_response"),
        ("Premium", "gpr_response"),
        ("Broker survey", "survey_response"),
        ("GIMMI", "gimmi_response"),
        ("Answer", "out_of_scope_answer"),
    ):
        text = (state.get(key) or "").strip()
        if text:
            parts.append(f"## {label}\n{text}")
    return "\n\n".join(parts)


def _fmt_cell(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return "" if v is None else str(v)


def _compact_rows(rows: List[Dict[str, Any]], max_rows: int = _MAX_DIGEST_ROWS) -> str:
    """Serialize result rows as a compact pipe table instead of a list of dicts.

    A list of dicts repeats every column name on every row — at 60 rows × 4
    lenses that's most of the digest prompt. The pipe table states each column
    once, and columns that are constant across all rows (carrier, country,
    year filters echoed back by SQL) are factored out into a single
    ``constants:`` line. Same information, a fraction of the tokens.
    """
    total = len(rows)
    rows = [r if isinstance(r, dict) else {"value": r} for r in list(rows)[:max_rows]]
    if not rows:
        return ""
    cols: List[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    consts: Dict[str, str] = {}
    if len(rows) > 1:
        for c in cols:
            vals = {_fmt_cell(r.get(c)) for r in rows}
            if len(vals) == 1:
                consts[c] = next(iter(vals))
    var_cols = [c for c in cols if c not in consts] or cols[:1]

    lines: List[str] = []
    if consts:
        lines.append("constants: " + ", ".join(f"{k}={v}" for k, v in consts.items()))
    if total > max_rows:
        lines.append(f"(showing first {max_rows} of {total} rows)")
    lines.append(" | ".join(var_cols))
    for r in rows:
        lines.append(" | ".join(_fmt_cell(r.get(c)) for c in var_cols))
    return "\n".join(lines)


def _gather_rows(state: AgentState) -> Dict[str, str]:
    """All available result sets, keyed by lens and serialized compactly, so the
    model can build timelines, country/product maps, and premium-vs-perception
    positioning from real rows without paying dict-per-row token overhead."""
    data: Dict[str, str] = {}
    for label, key in (
        ("premium", "gpr_query_result"),
        ("survey", "survey_query_result"),
        ("combined", "combined_result"),
        ("gimmi", "gimmi_query_result"),
    ):
        rows = state.get(key)
        if rows:
            table = _compact_rows(list(rows))
            if table:
                data[label] = table
    return data


def boardroom_node(state: AgentState) -> Dict[str, Any]:
    """Distil the turn's answer into a `BoardroomDigest` when boardroom mode is on.

    CRITICAL: every non-success path must explicitly return ``{"boardroom": None}``.
    The chat graph uses a persistent checkpointer that *merges* state across turns,
    so returning ``{}`` here would leave a PRIOR turn's digest in the checkpoint and
    the UI would wrongly re-render a dashboard for a plain answer.
    """
    if not state.get("boardroom_mode"):
        return {"boardroom": None}

    commentary = _gather_commentary(state)
    if not commentary:
        # Nothing was answered (e.g. a clarify-only turn) — clear any stale digest.
        return {"boardroom": None}

    user_query = state["messages"][-1].content if state.get("messages") else ""
    route = state.get("current_route") or "analyst"
    rows = _gather_rows(state)

    # One bounded retry: a transient API/parse failure shouldn't cost the user
    # their dashboard when the underlying answer succeeded.
    for attempt in (1, 2):
        try:
            digest = _BOARDROOM_MODULE(
                user_query=user_query,
                route=route,
                commentary=commentary,
                sql_output=rows,
            )
            return {"boardroom": digest.model_dump()}
        except Exception as exc:  # noqa: BLE001 - never break the turn over a presentation step
            log_event(
                logger,
                "boardroom_digest_error",
                logging.WARNING if attempt == 1 else logging.ERROR,
                route=route,
                attempt=attempt,
                error=str(exc),
            )
    return {"boardroom": None}
