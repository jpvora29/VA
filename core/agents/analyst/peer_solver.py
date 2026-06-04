"""Peer-comparison solver agent.

The most tool-heavy path in the old monolith (resolve carrier -> resolve peers
-> carrier premium -> peer-average premium -> YoY) and the one that routinely
exhausted the shared step budget. Isolating it as a specialist with only the two
tools it needs and its own generous budget means a heavy peer comparison can no
longer starve the other lenses.
"""
from __future__ import annotations

from core.agents.analyst.common import run_solver
from core.schemas.analyst_subgraph import Evidence, SchemaSlice

# ~12 tool calls (each round is ~2 super-steps). Peer comparisons are the most
# tool-heavy analytical move, so this specialist gets the largest budget.
PEER_RECURSION_LIMIT = 24

_ROLE = (
    "You are a peer-comparison specialist for insurance carriers. You compute a "
    "carrier's metric against its peer-group AVERAGE for the same slice, using "
    "the Peers table to resolve the peer set, and (when asked) how that gap moves "
    "year over year."
)


def solve_peer(
    *,
    model,
    question: str,
    sub_question: str,
    lens: str,
    flow: str,
    route: str,
    schema_slice: SchemaSlice,
    prior_digest: str = "",
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
        recursion_limit=PEER_RECURSION_LIMIT,
        peer_only=True,
        prior_digest=prior_digest,
    )
