"""Chartwright — the chart specialist, with a context window of its own.

Charting used to be a passenger on somebody else's prompt: the flow's chart rules,
all six per-type guidance blocks, and a fat all-types schema, evaluated inside a
turn already carrying a warehouse schema and a domain rulebook. It picked the type
and mapped the fields in one pass and got both wrong often enough that
`ChartSpecCritic` exists to repair the result.

Chartwright is a small, dedicated agent instead. Its whole context is the question,
a role-classified description of the result set, and one tool per chart type the
data can actually support — nothing about SQL, peers, or the warehouse. It answers
the only question it is asked: *which picture, drawn from which columns?*

    rows ─► profile (deterministic) ─► offer the supportable types
                                          │
                                          ▼
                                     select (LLM, ONE tool call)
                                          │
                                          ▼
                                     ground (deterministic) ─► spec

`select` is the only step that touches a model, and it is injected, so the whole
pipeline tests without one. A rejected or absent call returns an empty spec, which
is the caller's signal to fall back to the previous chart path — Chartwright never
guesses a chart it could not ground.

Flag: ``CHART_AGENT`` = ``on`` (default) | ``off`` (restores the two-phase path).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from core.charts.catalog import catalog_text, tool_schemas
from core.charts.grounding import ChartGrounding, ground_chart_call
from core.charts.profile import ColumnProfile, build_profile, sample_values, to_frame
from core.observability import log_event
from logger import get_logger

logger = get_logger(__name__)

#: What the status line calls this agent. One name, used by the UI and the logs.
AGENT_NAME = "Chartwright"


def chart_agent_mode() -> str:
    """`on` (default) or `off` — see the module docstring."""
    return os.getenv("CHART_AGENT", "on").strip().lower()


def chart_agent_enabled() -> bool:
    return chart_agent_mode() != "off"


_PROMPT = """
[ROLE]
You are {name}, a data-visualization specialist. You choose the ONE chart that
answers the user's question from the result set described below, and you say which
columns go on which axis. You do not write SQL, you do not compute or quote any
number, and you do not describe what the data shows — you design the picture.

[HOW TO CHOOSE]
- Call EXACTLY ONE tool: the chart type that answers the question. Every tool
  offered below is one the data can support; a type not listed is not drawable
  from this result, so do not ask for it.
- If nothing here answers the question — the result is a single figure, a lookup,
  or a list with nothing to compare — make NO tool call and reply with the single
  word NONE. A chart nobody needs is worse than no chart.
- Every column you name must be one of the values offered for that argument.
- A legend is only worth its space when the reader must compare the things in it.
  Prefer no series over a legend of near-identical lines.
- The title should name the measure, the cut and the period.

[THE RESULT SET]
{data}

[CHART TYPES AVAILABLE FOR THIS RESULT]
{catalog}
""".strip()


class ChartSelector(Protocol):
    """Chooses one chart tool call. Returns `(tool_name, arguments)` or None."""

    def select(self, request: "ChartRequest") -> Optional[Tuple[str, Dict[str, Any]]]:
        ...


@dataclass(frozen=True)
class ChartRequest:
    """Everything the selector needs to design one chart."""

    user_query: str
    profile: ColumnProfile
    data_description: str
    schemas: Sequence[Mapping[str, Any]]

    def prompt(self) -> str:
        return _PROMPT.format(
            name=AGENT_NAME,
            data=self.data_description,
            catalog=catalog_text(self.profile),
        )


class LLMChartSelector:
    """Binds the supportable chart types to the model and reads back its call."""

    def __init__(self, *, llm: Optional[Any] = None, tier: str = "balanced") -> None:
        self._llm = llm
        self._tier = tier

    def _client(self) -> Any:
        # Lazy: importing this module must not pull the credential layer.
        if self._llm is not None:
            return self._llm
        from core.llm import tier_client

        return tier_client(self._tier)

    def select(self, request: ChartRequest) -> Optional[Tuple[str, Dict[str, Any]]]:
        from langchain_core.messages import HumanMessage, SystemMessage

        if not request.schemas:
            return None
        messages = [
            SystemMessage(content=request.prompt()),
            HumanMessage(content=f"Question: {request.user_query}"),
        ]
        response = self._client().bind_tools(list(request.schemas)).invoke(messages)
        for call in getattr(response, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
            if name:
                return str(name), dict(args or {})
        return None


@dataclass(frozen=True)
class ChartTurn:
    """What Chartwright produced for one result set."""

    spec: Dict[str, Any] = field(default_factory=dict)
    tool: str = ""
    repairs: Tuple[str, ...] = ()
    rejected: Tuple[str, ...] = ()
    # True when the agent read the data and concluded there is no chart in it —
    # a decision, not a failure, so the caller must NOT fall back and try again.
    declined: bool = False

    @property
    def drawn(self) -> bool:
        return bool(self.spec)


class Chartwright:
    """The chart specialist. Every collaborator is injected, so this tests dry."""

    def __init__(self, *, selector: Optional[ChartSelector] = None) -> None:
        self._selector = selector if selector is not None else LLMChartSelector()

    def design(
        self, *, user_query: str, rows: Sequence[Mapping[str, Any]]
    ) -> ChartTurn:
        """Design one chart for `rows`, or return an empty turn."""
        frame = to_frame(rows)
        profile = build_profile(frame)
        if not profile.chartable:
            # Nothing to draw, and we know it without asking a model.
            return ChartTurn(declined=True)

        schemas = tool_schemas(profile)
        if not schemas:
            return ChartTurn(rejected=("no chart type fits this result",))

        request = ChartRequest(
            user_query=user_query,
            profile=profile,
            data_description=profile.describe(sample_values(frame, profile)),
            schemas=schemas,
        )
        try:
            selected = self._selector.select(request)
        except Exception as exc:  # noqa: BLE001 - a chart must never sink a turn
            logger.debug("%s selection failed: %s", AGENT_NAME, exc)
            return ChartTurn(rejected=(f"selection failed: {exc}",))

        if selected is None:
            # The agent looked and said there is no chart here.
            return ChartTurn(declined=True)

        tool_name, arguments = selected
        grounding: ChartGrounding = ground_chart_call(tool_name, arguments, profile)
        if not grounding.ok:
            return ChartTurn(
                tool=tool_name,
                rejected=tuple(f"{r.name}: {r.reason}" for r in grounding.rejected),
            )

        assert grounding.chart is not None  # narrowed by `ok`
        return ChartTurn(
            spec=dict(grounding.chart.spec),
            tool=tool_name,
            repairs=grounding.chart.repairs,
        )


def design_chart(
    *,
    user_query: str,
    rows: Sequence[Mapping[str, Any]],
    agent: Optional[Chartwright] = None,
    node: str = "chartwright",
) -> ChartTurn:
    """Run Chartwright over `rows` and log what it decided. Never raises."""
    try:
        turn = (agent or Chartwright()).design(user_query=user_query, rows=rows)
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s failed", AGENT_NAME)
        return ChartTurn(rejected=(str(exc),))

    log_event(
        logger,
        "chart_designed",
        node=node,
        agent=AGENT_NAME,
        tool=turn.tool,
        chart_type=turn.spec.get("chart_type", ""),
        repairs=list(turn.repairs),
        rejected=list(turn.rejected),
        declined=turn.declined,
        rows=len(rows or []),
    )
    return turn
