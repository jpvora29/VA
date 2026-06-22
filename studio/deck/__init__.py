"""Deck model + builder — the shared slide contract for screen and PPT export."""
from __future__ import annotations

from studio.deck.build import build_deck, build_qbr_deck
from studio.deck.model import (
    BulletsBlock,
    CalloutBlock,
    CardsBlock,
    ChartBlock,
    CommentaryBlock,
    DeckSpec,
    KpiBlock,
    SlideSpec,
    SwotBlock,
    TableBlock,
)

__all__ = [
    "DeckSpec",
    "SlideSpec",
    "KpiBlock",
    "ChartBlock",
    "TableBlock",
    "CommentaryBlock",
    "BulletsBlock",
    "CalloutBlock",
    "SwotBlock",
    "CardsBlock",
    "build_qbr_deck",
    "build_deck",
]
