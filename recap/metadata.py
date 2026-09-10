"""What a deck says about itself on its cover slide.

The pipeline wants to know whose review this was and which period it covered: the
noise filter uses the client and company names to tell content from branding, and the
recap's title and executive summary read the period back to the user.

Asking for all six by hand is six fields to fill in before anything can start, and a
QBR cover slide already carries them. So the cover is parsed on upload, best-effort,
and what it finds is shown back as chips the user can see — a wrong guess is visible
before Generate is pressed rather than discovered in the finished deck.

Pure functions over bytes: no Dash, no disk, no model.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import List, Tuple

from pptx import Presentation

logger = logging.getLogger(__name__)

#: Words that are the deck's furniture, not the client's name.
_FURNITURE = re.compile(r"\b(Q[1-4]|H[12]|Annual|QBR|Review|Meeting|Recap|20\d{2})\b", re.I)

_PERIOD = re.compile(r"\b(Q[1-4]|H[12]|Annual)\b", re.I)
_YEAR = re.compile(r"\b(20\d{2})\b")
_PERIOD_WITH_YEAR = re.compile(r"\b((?:Q[1-4]|H[12]|Annual)\s*20\d{2})\b", re.I)
_ISO_DATE = re.compile(r"\b(\d{4}[-/]\d{2}[-/]\d{2})\b")


@dataclass(frozen=True)
class DeckMetadata:
    """The cover slide's answer to "whose review, and when"."""

    client_name: str = ""
    company_name: str = ""
    period_label: str = ""
    quarter: str = ""
    year: str = ""
    meeting_date: str = ""

    def as_store(self) -> dict:
        return asdict(self)

    @classmethod
    def from_store(cls, data: dict | None) -> "DeckMetadata":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v or "" for k, v in (data or {}).items() if k in known})

    def found(self) -> List[Tuple[str, str]]:
        """The fields that were actually detected, in display order."""
        return [(f.name, getattr(self, f.name)) for f in fields(self) if getattr(self, f.name)]

    def is_empty(self) -> bool:
        return not self.found()


def read_cover(pptx_bytes: bytes) -> DeckMetadata:
    """Parse the first slide of a QBR deck for whatever metadata it states.

    Never raises: a deck that will not open, or one with no cover slide, simply
    contributes nothing — the run can still proceed with what the user typed or with
    nothing at all.
    """
    try:
        presentation = Presentation(io.BytesIO(pptx_bytes))
        slides = list(presentation.slides)
    except Exception as exc:  # noqa: BLE001 - a bad cover must not block an upload
        logger.warning("Cover-slide extraction failed: %s", exc)
        return DeckMetadata()

    if not slides:
        return DeckMetadata()

    slide = slides[0]
    period = _read_period(_all_text(slide))
    names = _read_names(slide)
    return DeckMetadata(**period, **names)


def deck_id_for(filename: str, index: int = 0) -> str:
    """The identifier a deck is filed under: a slug of its name, made unique.

    Every artefact the run writes is named from this, so it has to be filesystem-safe
    and it has to differ between two decks the user uploaded together — which two
    quarters exported from the same template will not do on name alone.
    """
    stem = re.sub(r"[^a-z0-9_]+", "_", Path(filename or "").stem.lower()).strip("_")
    return f"{stem or 'deck'}_{index}"


# ── the two readings ─────────────────────────────────────────────────────────


def _all_text(slide) -> str:
    """Every line of text on the slide, joined — what the period patterns run over."""
    return " | ".join(
        shape.text_frame.text.strip()
        for shape in slide.shapes
        if shape.has_text_frame and shape.text_frame.text.strip()
    )


def _read_period(text: str) -> dict:
    """Quarter, year, a free-form period label, and the meeting date."""
    quarter = _PERIOD.search(text)
    year = _YEAR.search(text)
    date = _ISO_DATE.search(text)

    found = {
        "quarter": quarter.group(1).upper() if quarter else "",
        "year": year.group(1) if year else "",
        "meeting_date": date.group(1).replace("/", "-") if date else "",
        "period_label": "",
    }
    # A period label is only worth carrying when quarter and year are not both known:
    # with both, it says the same thing twice and the recap title reads it twice.
    if not (found["quarter"] and found["year"]):
        label = _PERIOD_WITH_YEAR.search(text)
        found["period_label"] = label.group(1).strip() if label else ""
    return found


def _read_names(slide) -> dict:
    """The client and the company, read from the cover's title and subtitle.

    Placeholder 0 is the title and 1 the subtitle in every deck built from a template,
    which is what makes this more reliable than matching prose: the title names the
    client (once its QBR furniture is stripped), the subtitle names Marsh.
    """
    client = company = ""
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        index = _placeholder_index(shape)
        text = shape.text_frame.text.strip()
        if index is None or not text:
            continue
        if index == 0:
            candidate = _FURNITURE.sub("", text).strip(" |-_:")
            client = client or (candidate if len(candidate) > 2 else "")
        elif index == 1:
            first_line = text.split("\n")[0].strip()
            if "marsh" in first_line.lower():
                company = company or first_line
            else:
                client = client or first_line
    return {"client_name": client, "company_name": company}


def _placeholder_index(shape) -> int | None:
    """A shape's placeholder index, or None when it is not a placeholder."""
    try:
        placeholder = shape.placeholder_format
        return None if placeholder is None else placeholder.idx
    except (AttributeError, ValueError):
        return None
