"""Custom-peer override directive — shared by the deterministic SQL agents and
the analyst solver.

When a user pins a hand-picked peer set via the UI "Custom Peers" dialog, every
peer comparison in that conversation must benchmark against EXACTLY that set
instead of resolving the peer group from the ``Peers`` table. This renders that
instruction as a prompt block, injected wherever peer SQL is constructed
(``core/graph/gpr_subgraph.py``, ``core/graph/survey_subgraph.py``, and the
analyst ``_solver_prompt``).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def pinned_peers(
    custom_peers: Optional[Dict[str, Any]],
    flow: str,
    *,
    active: bool = True,
) -> Tuple[str, ...]:
    """The peer names pinned for `flow`, or ``()`` when there is no active override.

    The one place that decides whether an override applies. The prompt directive
    below renders it for the SQL path; the analytics tool path passes the same
    tuple straight to the peer primitives, so both benchmark the identical set.
    """
    if not active or not custom_peers:
        return ()
    if (custom_peers.get("flow") or "").lower() != (flow or "").lower():
        return ()
    return tuple(
        str(peer).strip()
        for peer in (custom_peers.get("peers") or [])
        if str(peer).strip()
    )


def custom_peer_directive(
    custom_peers: Optional[Dict[str, Any]],
    flow: str,
    *,
    active: bool = True,
) -> str:
    """Prompt block pinning the peer set to the user's selection, or ``""``.

    Returns an empty string — so callers can concatenate unconditionally — when
    there is no active override, the override targets a different ``flow``, or it
    carries no peers. ``flow`` is "gpr" or "survey"; the pinned peers are
    ``Carrier_Group`` values for GPR and ``Carrier`` values for survey.
    """
    peers = pinned_peers(custom_peers, flow, active=active)
    if not peers:
        return ""

    carrier = (custom_peers or {}).get("carrier") or "the selected carrier"
    country = custom_peers.get("country")
    peer_col = "Carrier_Group" if (flow or "").lower() == "gpr" else "Carrier"
    peer_list = ", ".join(f"'{p}'" for p in peers)
    country_note = f" in {country}" if country else ""

    return (
        "[CUSTOM PEER OVERRIDE — HIGHEST PRIORITY]\n"
        f"The user has explicitly pinned the peer set for {carrier}{country_note}. "
        "For ANY peer average / peer comparison in this query, use EXACTLY this "
        "peer set and DO NOT query the `Peers` table to resolve peers:\n"
        f"  {peer_col} IN ({peer_list})\n"
        "- Apply the SAME non-carrier user filters (year, country, product, "
        "segment, etc.) to BOTH the carrier leg and the peer-average leg.\n"
        "- Match case-insensitively and trimmed: "
        f"LOWER(TRIM({peer_col})) IN (the lower/trimmed pinned names).\n"
        "- Confidentiality still applies: report ONLY the aggregate peer average, "
        "never an individual peer name."
    )
