"""The two output shapes, as data.

Everything up to the last phase is identical between them; only three knobs differ,
so a mode is a record rather than a second pipeline. Adding a third output shape is a
new :class:`MoMMode` plus a prompt/body writer in :mod:`mom.summariser` — not an edit
to :mod:`mom.pipeline`.

``source`` is the document the user uploads alongside the deck, and it is what the
workspace's document-type toggle picks: an AI-generated summary of the call reads
slide by slide, hand-written self notes read section by section.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class MoMMode:
    """One end-to-end output shape."""

    id: str
    label: str            # what the workspace's document-type toggle shows
    hint: str             # the one-line explanation under it
    accept: str           # file extensions the notes upload accepts
    granularity: str      # "slide" | "section" — the unit a PPT JSON file holds
    summary: str          # "skill" | "carrier_marsh" — which DOCX body gets written
    sections: Tuple[str, ...]   # the body headings that DOCX will have


AI_SUMMARY = MoMMode(
    id="ai_summary",
    label="AI Summary PDF",
    hint="A meeting summary produced by Teams, Zoom or Copilot.",
    accept=".pdf",
    granularity="slide",
    summary="skill",
    sections=("Strategy & Initiatives", "Country / Product / Region", "Key Takeaways"),
)

SELF_NOTES = MoMMode(
    id="self_notes",
    label="Self Notes",
    hint="Your own typed notes. Photographed handwriting cannot be read.",
    accept=".pdf,.docx",
    granularity="section",
    summary="carrier_marsh",
    sections=("<Carrier>", "Marsh Update"),
)

MODES: Tuple[MoMMode, ...] = (AI_SUMMARY, SELF_NOTES)

_BY_ID: Dict[str, MoMMode] = {mode.id: mode for mode in MODES}

DEFAULT_MODE = AI_SUMMARY.id


def resolve_mode(mode_id: str | None) -> MoMMode:
    """The mode for a stored id, falling back to the default rather than raising."""
    return _BY_ID.get(mode_id or "", _BY_ID[DEFAULT_MODE])
