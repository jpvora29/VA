"""Peer-comparison solver agent.

The most tool-heavy path in the old monolith (resolve carrier -> resolve peers
-> carrier premium -> peer-average premium -> YoY) and the one that routinely
exhausted the shared step budget. Isolating it as a specialist with only the two
tools it needs and its own generous budget means a heavy peer comparison can no
longer starve the other lenses.
"""
from __future__ import annotations

from typing import Optional

from core.agents.analyst.common import run_solver
from core.schemas.analyst_subgraph import Evidence, SchemaSlice

# ~12 tool calls (each round is ~2 super-steps). Peer comparisons are the most
# tool-heavy analytical move, so this specialist gets the largest budget.
PEER_RECURSION_LIMIT = 24

_ROLE = (
    "You are a peer-comparison specialist for insurance carriers. You compute a "
    "carrier's metric against its peer-group AVERAGE for the same slice, and "
    "(when asked) how that gap moves year over year.\n"
    "HOW TO GET THE PEER AVERAGE: call compute_metric with "
    "name='compute_peer_average_total' for premium (the average of each peer's "
    "TOTAL — the like-for-like benchmark for an additive measure) or "
    "name='compute_peer_average' for a survey score (the average per response). "
    "It resolves the peer set from the Peers table for you, scopes it to the "
    "selected country, honours any pinned custom peer set, and returns an "
    "aggregate that never carries a peer name. Pair it with the carrier's own "
    "figure from compute_breakdown (or compute_attribute_breakdown for a score) "
    "so both legs come from the same signed-off definitions.\n"
    "ONLY IF a computed leg comes back empty do you fall back to run_sql. "
    "Peers.Overall_Peer_Group is meant to mirror GPR.Carrier_Group but is not "
    "always byte-identical, so hand-written peer SQL must match with "
    "LOWER(TRIM(...)) on BOTH sides. If the peer-average leg is empty/NULL while "
    "the carrier leg has data, the names diverge beyond case/space: pull the "
    "DISTINCT Overall_Peer_Group values and call resolve_value(flow='gpr', "
    "column='Carrier_Group', term=<each peer value>) to map them to the canonical "
    "GPR spelling, then re-run filtered on the resolved names. Never report a peer "
    "average of zero/NULL without first attempting this reconciliation."
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
        recursion_limit=PEER_RECURSION_LIMIT,
        peer_only=True,
        prior_digest=prior_digest,
        custom_peers=custom_peers,
        custom_peers_active=custom_peers_active,
    )
