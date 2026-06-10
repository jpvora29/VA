"""Boardroom digest node — staged generation.

Terminal enrichment step that runs after the route's insight writer (and the
follow-up node) when Boardroom Mode is active for the turn. It reshapes the
answer the rails already produced into a structured `BoardroomDigest` that the
UI renders as an inline dashboard card.

The digest is generated in STAGES instead of one giant call (which reliably
under-filled the ~12-section optional schema — the model satisficed on the
first fields and left the widget tail null even when the data supported it):

  1. CORE call — title/headline/KPIs/insights/commentary/risks (always).
  2. Deterministic signal detection over the RAW rows decides which widgets
     the data actually supports (>=2 periods -> timeline, >=2 countries or
     products -> opportunity map + radar, premium+perception -> positioning,
     >=2 carrier-ish values or peer talk -> comparison, any carrier ->
     battlecards).
  3. One SMALL per-widget call per detected signal; each has one output, so it
     cannot under-fill. A failed widget is skipped, never fatal.

All calls run on the deterministic LM (temperature 0): the digest is
fact-bearing presentation, and run-to-run widget variance was one of the
reported inconsistencies. Each stage records its token usage.

It is a strict no-op when `boardroom_mode` is False, so it can sit on the single
terminal edge of the main graph without affecting normal turns.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set, Tuple

import dspy

from core.initialization import Initialization
from core.observability import log_event
from core.schemas.boardroom import (
    BoardroomBattlecardsSignature,
    BoardroomComparisonSignature,
    BoardroomCoreSignature,
    BoardroomDigest,
    BoardroomOpportunitiesSignature,
    BoardroomOpportunityMapSignature,
    BoardroomPositioningSignature,
    BoardroomTimelineSignature,
)
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)

# Cap rows handed to the LLM so a wide result set can't blow the context window;
# the digest only needs a representative sample to format KPIs from.
_MAX_DIGEST_ROWS = 60

# Stateless predictors — instantiate once and reuse across turns. The core keeps
# ChainOfThought (it synthesises); the widgets are focused extractions, so plain
# Predict keeps them cheap.
_CORE_PREDICTOR = dspy.ChainOfThought(BoardroomCoreSignature)
_WIDGET_PREDICTORS: Dict[str, Tuple[Any, str]] = {
    "timeline": (dspy.Predict(BoardroomTimelineSignature), "timeline"),
    "opportunity_map": (
        dspy.Predict(BoardroomOpportunityMapSignature),
        "opportunity_map",
    ),
    "opportunities": (
        dspy.Predict(BoardroomOpportunitiesSignature),
        "opportunities",
    ),
    "positioning": (dspy.Predict(BoardroomPositioningSignature), "positioning"),
    "comparison": (dspy.Predict(BoardroomComparisonSignature), "comparison"),
    "battlecards": (dspy.Predict(BoardroomBattlecardsSignature), "battlecards"),
}


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


# How many analyst evidence sets the digest prompt carries. Each is a compact
# pipe table capped at _MAX_DIGEST_ROWS rows; beyond this the marginal widget
# signal isn't worth the tokens.
_MAX_EVIDENCE_SETS = 8


def _collect_row_sets(state: AgentState) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """All available RAW result sets, keyed by lens.

    Analyst turns carry `analyst_evidence` — EVERY query the solvers ran, one
    entry per lens. That is the full signal the advanced widgets need (timeline
    wants multi-year rows, the opportunity map wants multi-country/product rows),
    so when it is present it replaces the per-flow `*_query_result` fields, which
    only ever hold the FIRST result set per flow."""
    evidence = state.get("analyst_evidence") or []
    if evidence:
        sets: List[Tuple[str, List[Dict[str, Any]]]] = []
        seen_sql: set = set()
        for i, item in enumerate(evidence):
            if len(sets) >= _MAX_EVIDENCE_SETS:
                break
            rows = item.get("rows") or []
            sql_key = " ".join(str(item.get("sql", "")).split()).lower()
            if not rows or (sql_key and sql_key in seen_sql):
                continue
            seen_sql.add(sql_key)
            flow = item.get("flow") or "gpr"
            lens = item.get("lens") or f"query_{i + 1}"
            key = f"{flow}:{lens}"
            if any(k == key for k, _ in sets):  # same lens may run several queries
                key = f"{key}#{i + 1}"
            sets.append((key, list(rows)))
        if sets:
            return sets

    sets = []
    for label, key in (
        ("premium", "gpr_query_result"),
        ("survey", "survey_query_result"),
        ("combined", "combined_result"),
        ("gimmi", "gimmi_query_result"),
    ):
        rows = state.get(key)
        if rows and isinstance(rows, list):
            sets.append((label, list(rows)))
    return sets


def _gather_rows(state: AgentState) -> Dict[str, str]:
    """All available result sets, keyed by lens and serialized compactly, so the
    model can build timelines, country/product maps, and premium-vs-perception
    positioning from real rows without paying dict-per-row token overhead."""
    data: Dict[str, str] = {}
    for key, rows in _collect_row_sets(state):
        table = _compact_rows(rows)
        if table:
            data[key] = table
    return data


# ── deterministic widget-signal detection ───────────────────────────────────
#
# Column-name shapes per signal. Values are counted across ALL result sets, so
# a multi-year trend in one lens and a multi-country split in another both fire.
_PERIOD_COLS = re.compile(r"(?i)year|quarter|month|period|date")
_GEO_COLS = re.compile(r"(?i)country|market|region")
_PRODUCT_COLS = re.compile(r"(?i)product|line|cover|practice|lob")
_CARRIER_COLS = re.compile(r"(?i)carrier|peer|group")
_PREMIUM_COLS = re.compile(r"(?i)premium|sow|wallet|appetite|gpr")
_PERCEPTION_COLS = re.compile(r"(?i)score|nps|perception|rating")

# Rows scanned per result set when counting distinct signal values.
_SIGNAL_SCAN_ROWS = 200


def _distinct_values(
    row_sets: List[Tuple[str, List[Dict[str, Any]]]], pattern: "re.Pattern[str]"
) -> Set[str]:
    values: Set[str] = set()
    for _key, rows in row_sets:
        for row in rows[:_SIGNAL_SCAN_ROWS]:
            if not isinstance(row, dict):
                continue
            for col, val in row.items():
                if val is None or val == "":
                    continue
                if pattern.search(str(col)):
                    values.add(str(val).strip().lower())
    return values


def _has_column(
    row_sets: List[Tuple[str, List[Dict[str, Any]]]], pattern: "re.Pattern[str]"
) -> bool:
    for _key, rows in row_sets:
        for row in rows[:1]:
            if isinstance(row, dict) and any(pattern.search(str(c)) for c in row):
                return True
    return False


def detect_widget_signals(
    row_sets: List[Tuple[str, List[Dict[str, Any]]]], commentary: str
) -> Set[str]:
    """Which query-dependent widgets the data actually supports.

    Mirrors the population rules the old single-call prompt stated in prose —
    but decided deterministically, so a widget the data supports always gets
    its dedicated fill call instead of depending on the model's stamina."""
    signals: Set[str] = set()
    if len(_distinct_values(row_sets, _PERIOD_COLS)) >= 2:
        signals.add("timeline")
    geo = _distinct_values(row_sets, _GEO_COLS)
    products = _distinct_values(row_sets, _PRODUCT_COLS)
    if len(geo) >= 2 or len(products) >= 2:
        signals.add("opportunity_map")
        signals.add("opportunities")
    carriers = _distinct_values(row_sets, _CARRIER_COLS)
    if len(carriers) >= 2 or "peer" in (commentary or "").lower():
        signals.add("comparison")
    if carriers:
        signals.add("battlecards")
    if _has_column(row_sets, _PREMIUM_COLS) and _has_column(
        row_sets, _PERCEPTION_COLS
    ):
        signals.add("positioning")
    return signals


def _nullify_empty(name: str, widget: Any) -> Any:
    """Collapse a structurally-empty widget model to the None/[] the UI expects."""
    if widget is None:
        return None
    if name == "comparison" and not getattr(widget, "subjects", None):
        return None
    if name == "opportunity_map" and not (
        getattr(widget, "cells", None) or getattr(widget, "rows", None)
    ):
        return None
    if name == "positioning" and not getattr(widget, "points", None):
        return None
    return widget


def _fill_widgets(
    signals: "Set[str]", *, user_query: str, commentary: str, rows: Dict[str, str]
) -> Dict[str, Any]:
    """Run one small fill call per detected widget. Best-effort: a failed or
    structurally-empty widget is dropped, never fatal."""
    widgets: Dict[str, Any] = {}
    for name in sorted(signals):
        predictor, field = _WIDGET_PREDICTORS[name]
        try:
            with Initialization.dspy_usage(f"boardroom_widget:{name}", node="boardroom"):
                result = predictor(
                    user_query=user_query, commentary=commentary, sql_output=rows
                )
            widgets[name] = _nullify_empty(name, getattr(result, field, None))
        except Exception as exc:  # noqa: BLE001 - one widget must never sink the dashboard
            log_event(
                logger,
                "boardroom_widget_error",
                logging.WARNING,
                node="boardroom",
                widget=name,
                error=str(exc),
            )
    return widgets


def boardroom_node(state: AgentState) -> Dict[str, Any]:
    """Distil the turn's answer into a `BoardroomDigest` when boardroom mode is on.

    Staged: one core call (always), then one small call per widget the data
    supports — see the module docstring for why this replaced the single call.

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
    row_sets = _collect_row_sets(state)
    rows = {key: table for key, raw in row_sets if (table := _compact_rows(raw))}

    # Stage 1 — the core. One bounded retry: a transient API/parse failure
    # shouldn't cost the user their dashboard when the answer succeeded.
    core = None
    for attempt in (1, 2):
        try:
            with Initialization.dspy_usage("boardroom_core", node="boardroom"):
                core = _CORE_PREDICTOR(
                    user_query=user_query,
                    route=route,
                    commentary=commentary,
                    sql_output=rows,
                ).core
            break
        except Exception as exc:  # noqa: BLE001 - never break the turn over a presentation step
            log_event(
                logger,
                "boardroom_digest_error",
                logging.WARNING if attempt == 1 else logging.ERROR,
                route=route,
                attempt=attempt,
                error=str(exc),
            )
    if core is None:
        return {"boardroom": None}

    # Stage 2+3 — deterministic widget selection, then one small call each.
    signals = detect_widget_signals(row_sets, commentary)
    widgets = _fill_widgets(
        signals, user_query=user_query, commentary=commentary, rows=rows
    )
    log_event(
        logger,
        "boardroom_digest_built",
        node="boardroom",
        route=route,
        signals=sorted(signals),
        filled=sorted(k for k, v in widgets.items() if v),
    )

    digest = BoardroomDigest(
        title=core.title,
        subtitle=core.subtitle,
        headline=core.headline,
        kpis=core.kpis,
        insights=core.insights,
        commentary=core.commentary,
        risks=core.risks,
        comparison=widgets.get("comparison"),
        battlecards=widgets.get("battlecards") or [],
        timeline=widgets.get("timeline") or [],
        opportunity_map=widgets.get("opportunity_map"),
        opportunities=widgets.get("opportunities") or [],
        positioning=widgets.get("positioning"),
    )
    return {"boardroom": digest.model_dump()}
