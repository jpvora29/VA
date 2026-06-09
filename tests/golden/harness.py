"""Golden-query trace harness (decisions doc #9).

Runs a query through the live graph and captures the five shadow-comparison
signals: **route**, **selected skills**, **resolved entities**, **per-node /
per-agent token count**, and the **post-(critic) chart spec**. `capture_trace`
returns a typed `GoldenTrace`; `tests/golden/diff.py` diffs two traces.

Design notes:
- Importable WITHOUT LLM credentials. The graph (`core.graph.main.LangGraph`) and
  state are imported lazily inside `capture_trace`, so `diff.py`, `GoldenTrace`,
  and the YAML loader work in any environment. `live_available()` reports whether
  a real run is possible.
- Skills are harvested from `skill_match` log events via a temporary handler;
  token totals come from the `core.observability` turn-sink (no log scraping).
- History turns run first on the SAME thread_id, so inheritance/topic-switch
  cases exercise the persistent checkpointer exactly as production does.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

QUERIES_PATH = Path(__file__).parent / "queries.yaml"
BASELINE_DIR = Path(__file__).parent / "baseline"


# ── Trace shape ──────────────────────────────────────────────────────────────

@dataclass
class GoldenTrace:
    """Captured signals for one query — the unit the shadow diff compares."""

    id: str
    query: str
    route: str = ""                       # routing_context.table_family
    depth: str = ""                       # routing_context.analysis_depth
    selected_skills: List[str] = field(default_factory=list)
    resolved_entities: Dict[str, Any] = field(default_factory=dict)
    token_total: int = 0
    token_by_agent: Dict[str, int] = field(default_factory=dict)
    chart_specs: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoldenTrace":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# ── Case loading ─────────────────────────────────────────────────────────────

def load_cases(path: Path = QUERIES_PATH) -> List[Dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(raw.get("golden_queries", []))


def live_available() -> bool:
    """True when a real graph run is possible (Azure creds present)."""
    return bool(os.getenv("API_KEY") and os.getenv("ENDPOINT") and os.getenv("DEPLOYMENT"))


# ── Capture helpers ──────────────────────────────────────────────────────────

class _SkillCaptureHandler(logging.Handler):
    """Collects the union of `skill_match.matched` skills emitted during a run."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.matched: set[str] = set()

    def emit(self, record: logging.LogRecord) -> None:
        fields = getattr(record, "event_fields", None)
        if not fields or fields.get("event") != "skill_match":
            return
        for name in fields.get("matched", []) or []:
            self.matched.add(str(name))


def _chart_signature(chart: Any) -> Optional[Dict[str, Any]]:
    """Normalize a ChartOutput (dict or pydantic) to {type, x, y, series}.

    Matches the SHAPE the renderer draws, so two specs that differ in prose but
    draw the same chart compare equal (the chart-architecture dedup idea).
    """
    if not chart:
        return None
    get = (lambda k: chart.get(k)) if isinstance(chart, dict) else (lambda k: getattr(chart, k, None))
    chart_type = get("chart_type")
    if not chart_type:
        return None
    return {
        "type": chart_type,
        "x": get("x") or "",
        "y": list(get("y") or []),
        "series": list(get("series") or []),
    }


def _extract_charts(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for key in ("analyst_charts", "gpr_chart", "survey_chart", "combined_chart"):
        value = state.get(key)
        items = value if isinstance(value, list) else [value]
        for item in items:
            sig = _chart_signature(item)
            if sig is not None:
                specs.append(sig)
    return specs


def _extract_entities(routing_context: Any) -> Dict[str, Any]:
    if routing_context is None:
        return {}
    get = (
        (lambda k: routing_context.get(k))
        if isinstance(routing_context, dict)
        else (lambda k: getattr(routing_context, k, None))
    )
    out = {
        "carrier": get("inherited_carrier"),
        "country": get("inherited_country"),
        "year": get("inherited_year"),
    }
    return {k: v for k, v in out.items() if v}


# ── Live capture ─────────────────────────────────────────────────────────────

def capture_trace(case: Dict[str, Any], *, workflow: Any = None) -> GoldenTrace:
    """Run one golden case through the graph and capture its trace.

    Requires LLM credentials (`live_available()`). `workflow` may be a shared
    `LangGraph` instance for speed; otherwise a fresh one is built.
    """
    from langchain_core.messages import HumanMessage  # lazy: avoid LLM import

    from core.graph.main import LangGraph
    from core.observability import reset_turn_sink, set_turn_sink
    from core.state.agent_state import AgentState

    trace = GoldenTrace(id=case["id"], query=case["query"])
    lg = workflow or LangGraph()
    thread_id = f"golden-{case['id']}-{uuid.uuid4().hex[:8]}"

    def _state(text: str) -> Any:
        return AgentState(
            messages=[HumanMessage(content=text)],
            user_id=None,
            survey_attempts=0,
            gpr_attempts=0,
            gimmi_attempts=0,
            custom_peers=None,
            custom_peers_active=False,
            boardroom_mode=False,
            analyst_charts=[],
            survey_chart={},
            gpr_chart={},
            combined_chart={},
            survey_query_result=[],
            gpr_query_result=[],
            combined_result=[],
        )

    # Per-turn token snapshot from the observability sink.
    snapshots: List[Dict[str, Any]] = []
    sink_token = set_turn_sink(lambda payload: snapshots.append(payload))
    handler = _SkillCaptureHandler()
    root = logging.getLogger()
    prev_level = root.level
    root.setLevel(logging.DEBUG)  # skill_match logs at DEBUG
    root.addHandler(handler)
    try:
        # Replay history on the same thread so inheritance uses the checkpointer.
        for prior in case.get("history", []) or []:
            lg.trigger_workflow(_state(prior), thread_id=thread_id)
        final = lg.trigger_workflow(_state(case["query"]), thread_id=thread_id)
    except Exception as exc:  # noqa: BLE001 - record, don't crash the suite
        trace.error = f"{type(exc).__name__}: {exc}"
        return trace
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)
        reset_turn_sink(sink_token)

    routing = final.get("routing_context")
    rget = (
        (lambda k: routing.get(k))
        if isinstance(routing, dict)
        else (lambda k: getattr(routing, k, None))
    )
    trace.route = str(rget("table_family") or final.get("current_route") or "")
    trace.depth = str(rget("analysis_depth") or "")
    trace.resolved_entities = _extract_entities(routing)
    trace.selected_skills = sorted(handler.matched)
    trace.chart_specs = _extract_charts(final)

    # Token totals come only from the LAST turn (the measured query); history
    # turns are setup. Each snapshot is {trace_id, fields, token}.
    if snapshots:
        last = snapshots[-1].get("token", {})
        trace.token_total = int((last.get("total") or {}).get("total_tokens", 0) or 0)
        trace.token_by_agent = {
            agent: int(stats.get("total_tokens", 0) or 0)
            for agent, stats in (last.get("by_agent") or {}).items()
        }
    return trace


def run_golden_set(
    cases: Optional[List[Dict[str, Any]]] = None,
) -> List[GoldenTrace]:
    """Capture traces for every golden case (one shared workflow)."""
    from core.graph.main import LangGraph

    cases = cases if cases is not None else load_cases()
    lg = LangGraph()
    return [capture_trace(case, workflow=lg) for case in cases]
