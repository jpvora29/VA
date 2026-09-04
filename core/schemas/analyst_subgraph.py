"""Handoff schemas for the multi-agent analyst subgraph.

The analyst subgraph (`core.graph.analyst_subgraph`) replaces the single ReAct
loop with specialized agents that hand structured context to each other:

  planner  ->  schema-identifier  ->  parallel solvers  ->  insight-writer

`SchemaIdentification` is what the schema-identifier LLM emits; the node turns
its `values_to_resolve` into grounded `resolved_values` (via
`core.mcp.tools.match_column_values`) to produce a `SchemaSlice`, the clean,
minimal grounding bundle every solver receives. `Evidence` is one executed
query + its rows, collected by the solvers and consumed by the writer.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict


class ColumnTerm(BaseModel):
    """A loose user term that must be matched to a column's exact valid values."""

    column: str = Field(description="Exact schema column the term filters on.")
    term: str = Field(description="The user's loose wording to resolve.")


class SchemaIdentification(BaseModel):
    """Structured output of the schema-relationship-identifier agent.

    Names the minimal schema surface the plan needs so the solvers don't have to
    rediscover it through exploratory tool calls.
    """

    tables: List[str] = Field(
        default_factory=list,
        description="Tables actually needed to answer the plan (e.g. ['GPR', 'Peers']).",
    )
    join_keys: List[str] = Field(
        default_factory=list,
        description=(
            "How the chosen tables relate, as short notes "
            "(e.g. 'Peers.Overall_Peer_Group values ARE GPR.Carrier_Group')."
        ),
    )
    values_to_resolve: List[ColumnTerm] = Field(
        default_factory=list,
        description="Dimension filters in the plan whose wording needs grounding.",
    )
    notes: str = Field(
        default="",
        description="Any other grounding note useful to the solvers (optional).",
    )


class SchemaSlice(BaseModel):
    """Grounded schema bundle passed to every solver (post-resolution)."""

    tables: List[str] = Field(default_factory=list)
    join_keys: List[str] = Field(default_factory=list)
    resolved_values: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="column -> exact valid values matched for the user's terms.",
    )
    notes: str = Field(default="")
    guard_zero_rows: bool = Field(
        default=False,
        description="True when this turn left a user-named entity unresolved, so a "
        "solver's 0-row result is worth ONE re-check for a wrong filter value. A "
        "clean turn's 0-row is taken as genuine 'no data' — no re-run loop.",
    )

    def as_prompt(self) -> str:
        """Render the slice for injection into a solver's system prompt."""
        lines: List[str] = []
        if self.tables:
            lines.append(f"Relevant tables: {', '.join(self.tables)}")
        if self.join_keys:
            lines.append("Table relationships:")
            lines.extend(f"  - {k}" for k in self.join_keys)
        if self.resolved_values:
            lines.append("Pre-resolved filter values (use these EXACT strings):")
            for column, values in self.resolved_values.items():
                if values:
                    lines.append(f"  - {column}: {', '.join(values)}")
        if self.notes:
            lines.append(f"Notes: {self.notes}")
        return "\n".join(lines) or "(no specific schema slice identified)"


class Evidence(TypedDict):
    """One executed query and the rows it returned, gathered by a solver.

    `rows` are ALREADY peer-redacted (`core.agents.common.peer_privacy`): a
    solver sees real peer names in its tool results because it needs them to
    write the next query, but what is recorded here -- and so what reaches the
    writer, the shown table and the charts -- names no individual peer.
    `redacted_peers` is the vocabulary that was removed, so the final prose can
    be scrubbed against exactly the names this turn actually touched.
    """

    flow: str
    sql: str
    rows: List[Any]
    lens: str
    redacted_peers: NotRequired[Tuple[str, ...]]
