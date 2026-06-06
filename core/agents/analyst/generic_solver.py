"""Generic per-lens solver agent.

Gathers the evidence for one non-peer analytical lens (market context, temporal
trend, dimensional breakdown, whitespace, opportunity, contradiction). Same
bounded-ReAct machinery as the peer solver but with the full read-only toolset
and a smaller budget, since these moves are typically 1-3 queries.
"""
from __future__ import annotations

from typing import Optional

from core.agents.analyst.common import run_solver
from core.schemas.analyst_subgraph import Evidence, SchemaSlice

# ~8 tool calls — non-peer lenses are usually a small number of focused queries.
GENERIC_RECURSION_LIMIT = 16

_ROLE = (
    "You are a focused insurance-data analyst. You retrieve exactly the rows that "
    "answer one analytical sub-question, following the lens shape provided."
)


def solve_generic(
    *,
    model,
    question: str,
    sub_question: str,
    lens: str,
    flow: str,
    route: str,
    schema_slice: SchemaSlice,
    prior_digest: str = "",
    custom_peers: Optional[dict] = None,
    custom_peers_active: bool = False,
) -> list[Evidence]:
    return run_solver(
        model=model,
        role=_ROLE,
        question=question,
        sub_question=sub_question,
        lens=lens,
        flow=flow,
        route=route,
        schema_slice=schema_slice,
        recursion_limit=GENERIC_RECURSION_LIMIT,
        peer_only=False,
        prior_digest=prior_digest,
        custom_peers=custom_peers,
        custom_peers_active=custom_peers_active,
    )
