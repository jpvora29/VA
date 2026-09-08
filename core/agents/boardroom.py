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
     the data actually supports (>=2 quarters -> quarterly performance, else
     >=2 periods -> timeline; premium split by product -> headroom + portfolio
     map; an industry dimension -> whitespace; >=2 carriers -> top carriers and
     comparison).
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

from core.boardroom.derive import complete_widget
from core.llm import Predictor
from core.observability import log_event
from core.schemas.boardroom import (
    BoardroomBattlecardsSignature,
    BoardroomComparisonSignature,
    BoardroomCoreSignature,
    BoardroomDigest,
    BoardroomTimelineSignature,
)
from core.schemas.boardroom_explainable import (
    BoardroomHeadroomSignature,
    BoardroomPortfolioMapSignature,
    BoardroomQuarterlySignature,
    BoardroomTopCarriersSignature,
    BoardroomWatchlistSignature,
    BoardroomWhitespaceSignature,
)
from core.scope import chips_from_state, chips_to_dicts
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)

# Cap rows handed to the LLM so a wide result set can't blow the context window;
# the digest only needs a representative sample to format KPIs from.
_MAX_DIGEST_ROWS = 60

# Stateless predictors — instantiate once and reuse across turns.
#
# Tier + reasoning follow the work: the core call synthesises the headline,
# insights and commentary, so it reasons on the reason tier; each widget fill is
# a focused extraction, so it answers directly on the fast tier.
_CORE_PREDICTOR = Predictor(
    BoardroomCoreSignature, tier="reason", reasoning=True,
    label="boardroom_core", node="boardroom",
)


# widget name -> (signature, the output field carrying its content).
#
# The explainable widgets REPLACE the score-based ones the roadmap retired: a new
# digest never asks for an opportunity radar, a 0-100 heatmap, or a positioning
# plot plotting share of wallet against a broker score (two unrelated measures on
# one chart - the Product Portfolio Map answers that question properly).
#
# Their schemas and renderers stay in the codebase so saved boards still open and
# the widget library can still add one by hand.
_WIDGET_SIGNATURES: Dict[str, Tuple[Any, str]] = {
    "watchlist": (BoardroomWatchlistSignature, "watchlist"),
    "headroom": (BoardroomHeadroomSignature, "headroom"),
    "whitespace": (BoardroomWhitespaceSignature, "whitespace"),
    "quarterly": (BoardroomQuarterlySignature, "quarterly"),
    "portfolio_map": (BoardroomPortfolioMapSignature, "portfolio_map"),
    "top_carriers": (BoardroomTopCarriersSignature, "top_carriers"),
    "timeline": (BoardroomTimelineSignature, "timeline"),
    "comparison": (BoardroomComparisonSignature, "comparison"),
    "battlecards": (BoardroomBattlecardsSignature, "battlecards"),
}

_WIDGET_PREDICTORS: Dict[str, Tuple[Predictor, str]] = {
    name: (
        Predictor(signature, tier="fast", label=f"boardroom_widget:{name}",
                  node="boardroom"),
        field,
    )
    for name, (signature, field) in _WIDGET_SIGNATURES.items()
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
_QUARTER_COLS = re.compile(r"(?i)quarter|qtr")
_GEO_COLS = re.compile(r"(?i)country|market|region")
_PRODUCT_COLS = re.compile(r"(?i)product|line|cover|practice|lob")
_INDUSTRY_COLS = re.compile(r"(?i)industry|sector|sic")
_CARRIER_COLS = re.compile(r"(?i)carrier|peer|group")
_PREMIUM_COLS = re.compile(r"(?i)premium|sow|wallet|appetite|gpr")
_PERCEPTION_COLS = re.compile(r"(?i)score|nps|perception|rating")

# A quarter label anywhere in a period column ("Q2 2026", "2026-Q2", "FY26 Q2").
_QUARTER_VALUE = re.compile(r"(?i)(^|[^a-z])q[1-4]([^a-z]|$)")

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


def quarter_labels(row_sets: List[Tuple[str, List[Dict[str, Any]]]]) -> Set[str]:
    """Distinct quarter labels in the rows — a quarter column, or 'Q2' in a period."""
    labels = {v for v in _distinct_values(row_sets, _QUARTER_COLS) if v}
    labels |= {
        v for v in _distinct_values(row_sets, _PERIOD_COLS) if _QUARTER_VALUE.search(v)
    }
    return labels


def detect_widget_signals(
    row_sets: List[Tuple[str, List[Dict[str, Any]]]], commentary: str
) -> Set[str]:
    """Which query-dependent widgets the data actually supports.

    Deterministic, so a widget the data supports always gets its dedicated fill
    call instead of depending on the model's stamina — and, just as importantly,
    so a widget the data CANNOT support is never manufactured: quarterly
    performance needs two real quarters, headroom needs premium split by product,
    whitespace needs an industry dimension.
    """
    signals: Set[str] = set()
    periods = _distinct_values(row_sets, _PERIOD_COLS)
    quarters = quarter_labels(row_sets)
    has_premium = _has_column(row_sets, _PREMIUM_COLS)
    has_perception = _has_column(row_sets, _PERCEPTION_COLS)

    # Quarterly performance is the QBR default; the annual timeline is the
    # fallback for data that carries no comparable quarters.
    if len(quarters) >= 2:
        signals.add("quarterly")
    elif len(periods) >= 2:
        signals.add("timeline")

    # A watch item needs a movement, so it needs two periods and a measure.
    if len(periods) >= 2 and (has_premium or has_perception):
        signals.add("watchlist")

    if has_premium and len(_distinct_values(row_sets, _PRODUCT_COLS)) >= 2:
        # Both product views: headroom ranks the money left on the table, the
        # portfolio map shows where the book sits against where it wins.
        signals.add("headroom")
        signals.add("portfolio_map")
    # An industry COLUMN is not an industry view. A result set that carries
    # `Industry` with one value in it (every row is Manufacturing, because the
    # question was about Manufacturing) cannot be ranked BY industry, and asking
    # for the widget anyway produced an Industry Focus page with nothing on it.
    if has_premium and len(_distinct_values(row_sets, _INDUSTRY_COLS)) >= 2:
        signals.add("whitespace")

    carriers = _distinct_values(row_sets, _CARRIER_COLS)
    if len(carriers) >= 2 or "peer" in (commentary or "").lower():
        signals.add("comparison")
    if carriers:
        signals.add("battlecards")
    if has_premium and len(carriers) >= 2:
        signals.add("top_carriers")
    return signals


# widget name -> the key holding its content. A widget with an EMPTY content key
# is dropped: an "explaining" panel that says the data cannot support it is still
# a panel the reader has to work past, and a page of them is a page the board
# should never have shown. Nothing is manufactured to fill the gap either — the
# page simply narrows to the steps the data does support.
_WIDGET_CONTENT_KEY: Dict[str, str] = {
    "comparison": "subjects",
    "portfolio_map": "bubbles",
    "top_carriers": "carriers",
    "watchlist": "items",
    "headroom": "rows",
    "whitespace": "rows",
    "quarterly": "rows",
}


def _nullify_empty(name: str, payload: Any) -> Any:
    """Drop a widget whose content is empty, whatever note came with it."""
    if not isinstance(payload, dict):
        return payload or None
    key = _WIDGET_CONTENT_KEY.get(name)
    if key is not None and not payload.get(key):
        return None
    return payload


def _fill_widgets(
    signals: "Set[str]", *, user_query: str, commentary: str, rows: Dict[str, str]
) -> Dict[str, Any]:
    """Run one small fill call per detected widget, then complete its numbers.

    Three steps per widget, in order: extract (the model), complete (arithmetic
    the model should not be trusted with — see `core.boardroom.derive`), drop if
    it ended up with nothing to show. Best-effort: a failed widget is skipped,
    never fatal.
    """
    widgets: Dict[str, Any] = {}
    for name in sorted(signals):
        predictor, field = _WIDGET_PREDICTORS[name]
        try:
            result = predictor(
                user_query=user_query, commentary=commentary, sql_output=rows
            )
            extracted = getattr(result, field, None)
            payload = extracted.model_dump() if hasattr(extracted, "model_dump") else extracted
            widgets[name] = _nullify_empty(name, complete_widget(name, payload))
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


def _turn_scope(state: AgentState):
    """The scope chips this dashboard was built from (the chat shows the same ones)."""
    peers = state.get("custom_peers") if state.get("custom_peers_active") else None
    return chips_from_state(state, peers)


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
        watchlist=widgets.get("watchlist"),
        headroom=widgets.get("headroom"),
        whitespace=widgets.get("whitespace"),
        quarterly=widgets.get("quarterly"),
        portfolio_map=widgets.get("portfolio_map"),
        top_carriers=widgets.get("top_carriers"),
        scope=chips_to_dicts(_turn_scope(state)),
    )
    return {"boardroom": digest.model_dump()}
