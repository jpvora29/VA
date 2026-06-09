"""Custom-peer carrier-mismatch HITL gate.

When the user has pinned a hand-picked peer set (UI "Custom Peers" dialog) but
then asks a peer question about a DIFFERENT carrier than the one the peers were
built for, blindly applying the pinned peers would be wrong. This deterministic
node sits between the rephraser and the router and, on a confident mismatch,
`interrupt()`s with a 3-way MCQ — exactly like `core.graph.hitl.clarify_gate`,
reusing the same interrupt → `clarify_card` → `Command(resume=...)` machinery.

Resume values:
- "Use database peers"  -> drop the override for this turn (custom_peers_active=False)
- "Use my selected peers" -> keep the override (custom_peers_active=True)
- a dict {"action": "use_custom", "custom_peers": {...}} -> the UI's "Pick new
  peers" path: replace the pinned set with a freshly chosen one and keep it active.

The gate is a no-op (pure pass-through) unless there is an active override, the
turn is a peer question, and a confidently-resolved carrier differs from the
pinned one — so confident, on-carrier turns are never interrupted.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, List, Optional

from langgraph.types import interrupt

from config.valid_values_config import valid_carriers, valid_groups_gpr
from core.observability import log_event
from logger import get_logger

if TYPE_CHECKING:
    from core.state.agent_state import AgentState

logger = get_logger(__name__)

# Tokens that signal the turn is actually a peer comparison. Mirrors the triggers
# in core/skills/catalog/gpr/gpr-peer-average.skill.md so the gate only fires
# when peers matter.
_PEER_TOKENS = (
    "peer",
    "peers",
    "competitor",
    "competition",
    "rival",
    "versus",
    " vs ",
    "vs.",
    "benchmark",
    "compare",
    "comparison",
    "against",
)

# Generic corporate/legal tokens that never disambiguate a carrier on their own
# (mirrors core.mcp.tools._GENERIC_TOKENS). Stripping them means a candidate is
# recognised by its distinctive token(s) — "zurich" for "ZURICH GROUP".
_GENERIC_TOKENS = frozenset(
    {
        "insurance", "insurer", "insurers", "assurance", "reinsurance",
        "group", "holdings", "holding", "company", "companies", "co",
        "ltd", "limited", "corporation", "corp", "incorporated", "inc",
        "plc", "pcl", "ag", "sa", "nv", "se", "general", "public",
        "and", "of", "the", "wholesale",
    }
)

_RESUME_DATABASE = "Use database peers"
_RESUME_CUSTOM = "Use my selected peers"
_RESUME_PICK_NEW = "Pick new peers"


def _is_peer_question(query: str) -> bool:
    lowered = f" {(query or '').lower()} "
    return any(token in lowered for token in _PEER_TOKENS)


def _distinctive_tokens(name: str) -> List[str]:
    toks = re.findall(r"[a-z0-9]+", (name or "").lower())
    distinctive = [t for t in toks if t not in _GENERIC_TOKENS]
    return distinctive or toks  # fall back to all tokens if every token is generic


def _named_carriers(query: str, flow: str) -> List[str]:
    """Valid carriers/groups whose distinctive tokens all appear as words in the
    query, most-specific (most tokens matched) first. Empty when none is named."""
    candidates = valid_groups_gpr if (flow or "").lower() == "gpr" else valid_carriers
    if not candidates:
        return []
    words = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    if not words:
        return []
    matched: List[tuple[int, str]] = []
    for cand in candidates:
        toks = _distinctive_tokens(cand)
        if toks and all(t in words for t in toks):
            matched.append((len(toks), cand))
    matched.sort(key=lambda pair: pair[0], reverse=True)
    return [cand for _, cand in matched]


def _mismatch_question(pinned_carrier: str, asked_carrier: str) -> dict:
    """MCQ payload for the carrier-mismatch interrupt (ClarifyQuestion shape)."""
    return {
        "kind": "custom_peer_mismatch",
        "header": "Custom peers",
        "question": (
            f"You pinned a custom peer set for {pinned_carrier}, but this question "
            f"is about {asked_carrier}. Which peers should I use?"
        ),
        "options": [
            {
                "label": _RESUME_DATABASE,
                "description": f"Use the database peer group for {asked_carrier}.",
            },
            {
                "label": _RESUME_CUSTOM,
                "description": f"Reuse the peers you picked for {pinned_carrier}.",
            },
            {
                "label": _RESUME_PICK_NEW,
                "description": "Open the Custom Peers dialog to choose a new set.",
            },
        ],
        "allow_free_text": False,
    }


def custom_peer_gate(state: "AgentState") -> "AgentState":
    """Interrupt on a confident carrier mismatch against the pinned peer set."""
    custom_peers = state.get("custom_peers")
    if (
        not state.get("custom_peers_active")
        or not custom_peers
        or not custom_peers.get("peers")
    ):
        return {}

    query = state["messages"][-1].content if state.get("messages") else ""
    if not _is_peer_question(query):
        return {}

    flow = custom_peers.get("flow") or "gpr"
    pinned = (custom_peers.get("carrier") or "").strip()
    named = _named_carriers(query, flow)
    # No carrier named, or the pinned carrier is among those named -> use the
    # pinned peers silently. Biasing toward the pinned carrier on ambiguity keeps
    # the gate from interrupting a turn that does concern the pinned carrier.
    if not named or any(n.strip().lower() == pinned.lower() for n in named):
        return {}
    asked = named[0]

    log_event(
        logger,
        "custom_peer_mismatch",
        node="custom_peer_gate",
        pinned=pinned,
        asked=asked,
    )
    # Pauses until the UI resumes with Command(resume=<label or dict>).
    answer = interrupt(_mismatch_question(pinned, asked))

    # Structured resume (UI "Pick new peers" path): replace the pinned set.
    if isinstance(answer, dict):
        new_peers = answer.get("custom_peers")
        updates: AgentState = {"custom_peers_active": True}
        if new_peers:
            updates["custom_peers"] = new_peers
        log_event(
            logger, "custom_peer_resumed", node="custom_peer_gate", choice="pick_new"
        )
        return updates

    if str(answer).strip() == _RESUME_DATABASE:
        log_event(
            logger, "custom_peer_resumed", node="custom_peer_gate", choice="database"
        )
        return {"custom_peers_active": False}

    log_event(logger, "custom_peer_resumed", node="custom_peer_gate", choice="custom")
    return {"custom_peers_active": True}
