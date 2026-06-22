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
) -> DeckSpec:
    from studio.content import build_content_spec, plan_deck

    spec = build_content_spec(result, carrier=carrier, country=country, year=year)
    return plan_deck(spec, result, report=report, cuts=cuts)


def build_qbr_deck(result, **kw) -> DeckSpec:
    """Back-compat wrapper — full QBR."""
    kw.pop("report", None)
    return build_deck(result, report="qbr", **kw)
