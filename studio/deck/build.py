"""Deck builder — delegates to the QBR content/story layer.

    facts (OverallResult)
        → build_content_spec  (evidence model: thesis, drivers, risks, actions, gaps)
        → plan_deck           (material slide selection, decision-oriented)
        → DeckSpec            (rendered on screen + exported to .pptx)

`report` is "qbr" (full agenda-driven deck) or "exec" (cover + executive summary).
Content imports are deferred to call time so the `studio.deck` package stays
import-light and cycle-free.
"""
from __future__ import annotations

from typing import Any, Optional

from studio.compute import OverallResult
from studio.deck.model import DeckSpec


def build_deck(
    result: OverallResult,
    *,
    carrier: Optional[str] = None,
    country: Optional[str] = None,
    year: Optional[Any] = None,
    report: str = "qbr",
    cuts=(),
    ai: bool = False,
    audience: str = "executive",
    meeting_length: str = "standard",
) -> DeckSpec:
    """Build the QBR deck. With ``ai=True`` *and* an LLM configured, the AI agents
    (selection → story → layout → critic) enhance the deterministic deck, each
    faithfulness-checked with a deterministic fallback; otherwise the exact
    deterministic path runs unchanged.
    """
    from dataclasses import replace

    from studio.content import build_content_spec, plan_deck

    spec = build_content_spec(result, carrier=carrier, country=country, year=year)

    use_ai = bool(ai)
    if use_ai:
        from studio.ai import llm_available

        use_ai = llm_available()

    if use_ai:
        from studio.ai import selection_agent

        order = selection_agent.select_sections(spec, audience=audience, meeting_length=meeting_length)
        if order:
            keep = set(order)
            filtered = tuple(f for f in spec.findings if f.section in keep)
            if filtered:  # never let the selection empty the deck
                spec = replace(spec, findings=filtered)

    deck = plan_deck(spec, result, report=report, cuts=cuts)

    if use_ai:
        from studio.ai import critic_agent, layout_agent, story_agent

        deck = story_agent.enhance_deck(deck, result, subject=carrier or result.subject)
        deck = layout_agent.enhance_deck(deck)
        deck = critic_agent.review_deck(deck)

    return deck


def build_qbr_deck(result, **kw) -> DeckSpec:
    """Back-compat wrapper — full QBR."""
    kw.pop("report", None)
    return build_deck(result, report="qbr", **kw)
