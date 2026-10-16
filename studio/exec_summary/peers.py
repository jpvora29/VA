"""Peer resolution — peers(focal carrier, country), never one flat list (design Section 3).

A carrier is benchmarked against a different set in Singapore than in Hong Kong, so the
map is keyed by country. The Setup page's per-market pin wins; a market without a pin
resolves its own group from the Peers table. A missing group is an explicit "none", which
the comparisons then report as an unavailable reference rather than a zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Sequence, Tuple

from studio.exec_summary.context import AnalysisContext

SOURCE_PINNED = "setup_pin"
SOURCE_TABLE = "peers_table"
SOURCE_NONE = "none"


@dataclass(frozen=True)
class PeerSet:
    country: str
    members: Tuple[str, ...]
    source: str

    @property
    def available(self) -> bool:
        return bool(self.members)


#: ``(flow, carrier, country, engine) -> [peer…]`` — the Peers-table lookup, injectable.
PeerLookup = Callable[[str, str, str, Any], Sequence[str]]


def peers_table_lookup(flow: str, carrier: str, country: str, engine: Any) -> Sequence[str]:
    from studio.data import peer_members

    return peer_members(flow, carrier, country=country, engine=engine)


def _clean(members: Sequence[str], carrier: str) -> Tuple[str, ...]:
    """Distinct members, focal carrier excluded, original order kept."""
    seen, out = set(), []
    for m in members:
        name = str(m).strip()
        if name and name.lower() != carrier.lower() and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return tuple(out)


def resolve_peer_set(context: AnalysisContext, country: str, engine: Any,
                     lookup: PeerLookup = peers_table_lookup) -> PeerSet:
    pinned = _clean(context.peer_pins.get(country) or (), context.carrier)
    if pinned:
        return PeerSet(country, pinned, SOURCE_PINNED)
    try:
        found = _clean(lookup(context.flow, context.carrier, country, engine), context.carrier)
    except Exception:  # noqa: BLE001 — a missing Peers table is "no peers", not a crash
        found = ()
    return PeerSet(country, found, SOURCE_TABLE if found else SOURCE_NONE)


def resolve_peer_sets(context: AnalysisContext, engine: Any,
                      lookup: PeerLookup = peers_table_lookup) -> Dict[str, PeerSet]:
    """One peer set per selected country, in the context's country order."""
    return {c: resolve_peer_set(context, c, engine, lookup) for c in context.countries}
