"""The peer-set rules shared by every surface that lets a user pick peers.

A benchmark of one or two carriers is not an aggregate — it is close enough to
naming them, which carrier-facing output may not do. Five is the floor the
disclosure rule needs and the smallest set an average means anything over.

Studio's setup form and the chatbot's Custom Peers dialog both enforce it, so
the rule (and its wording) lives here rather than in either UI.
"""
from __future__ import annotations

from typing import Sequence

MIN_CUSTOM_PEERS = 5
MIN_PEERS_MESSAGE = "Please select atleast 5 peers"


def count_peers(values: Sequence[str] | None) -> int:
    """How many real peers a picker holds — blanks are not selections."""
    return len([v for v in (values or []) if v])


def peers_are_enough(values: Sequence[str] | None) -> bool:
    """True when a peer set clears the minimum."""
    return count_peers(values) >= MIN_CUSTOM_PEERS


def peer_min_note(values: Sequence[str] | None) -> str:
    """The under-minimum warning for one peer set (``""`` when it is fine)."""
    return "" if peers_are_enough(values) else MIN_PEERS_MESSAGE


def peer_shortfall_note(values: Sequence[str] | None) -> str:
    """The same warning, saying how many more are needed (``""`` when fine).

    The dialog shows this next to a live count, where "3 more to go" is a more
    actionable line than restating the floor.
    """
    missing = MIN_CUSTOM_PEERS - count_peers(values)
    if missing <= 0:
        return ""
    return f"{MIN_PEERS_MESSAGE} — {missing} more to go"
