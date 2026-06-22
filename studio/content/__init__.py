"""QBR content/story layer: facts → evidence model → story planner → DeckSpec."""
from __future__ import annotations

from studio.content.evidence import build_content_spec
from studio.content.model import (
    Action,
    DataGap,
    Evidence,
    Finding,
    QBRContentSpec,
)
from studio.content.planner import plan_deck

__all__ = [
    "QBRContentSpec",
    "Finding",
    "Evidence",
    "Action",
    "DataGap",
    "build_content_spec",
    "plan_deck",
]
