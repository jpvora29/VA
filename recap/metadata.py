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

from recap.config import settings

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
    carrier: str = ""
    country_region: str = ""

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


def read_cover(pptx_bytes: bytes, filename: str = "") -> DeckMetadata:
    """Parse the first slide of a QBR deck for whatever metadata it states.

    ``filename`` is the fallback for the year, which a deck often states only in its
    name ("UK QBE QBR Europe 2026 Q2 v3.pptx").

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
    cover_text = _all_text(slide)
    period = _read_period(cover_text, filename)
    names = _read_names(slide)
    scope = _read_scope(cover_text, slides)
    return DeckMetadata(**period, **_client_from_scope(names, scope), **scope)


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


def _read_period(text: str, filename: str = "") -> dict:
    """Quarter, year, the period label, and the meeting date.

    The year falls back to the filename when the cover does not state it. The label
    is always filled when it can be — as written on the cover, else quarter + year —
    so recap titles and output filenames carry the whole period.
    """
    quarter = _PERIOD.search(text)
    year = _YEAR.search(text) or _YEAR.search(filename or "")
    date = _ISO_DATE.search(text)
    label = _PERIOD_WITH_YEAR.search(text)

    found = {
        "quarter": quarter.group(1).upper() if quarter else "",
        "year": year.group(1) if year else "",
        "meeting_date": date.group(1).replace("/", "-") if date else "",
    }
    if label:
        found["period_label"] = label.group(1).strip()
    else:
        found["period_label"] = " ".join(
            part for part in (found["quarter"], found["year"]) if part
        ) if found["quarter"] and found["year"] else ""
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


def _read_scope(cover_text: str, slides: list) -> dict:
    """The carrier and the country or region the review is about.

    The carrier is matched through every alias in ``assets/config.yaml`` ("AGCS",
    "Zurich UK", "AIG Talbot") to its canonical name: on the cover first, and across
    the whole deck only when the cover names none.

    The country or region is read from the cover ONLY. A body slide that merely
    mentions one ("Zurich has a US Surplus Lines licence") would otherwise become the
    scope, and the client label would read "Zurich North America". A region wins over
    a country — it is the broader scope, and the one the chip should show.
    """
    carrier = _carrier_named(cover_text)
    if not carrier:
        carrier = _carrier_named(" | ".join(_all_text(slide) for slide in slides))
    return {
        "carrier": carrier,
        "country_region": _first_named(cover_text, settings.regions + settings.countries),
    }


def _client_from_scope(names: dict, scope: dict) -> dict:
    """The client label as "<carrier> <country/region>" whenever either was found.

    Both come from the canonical lists, so they beat whatever the title placeholder
    held — and give the "QBE Europe" label recap titles and filenames want.
    """
    from_scope = " ".join(part for part in (scope["carrier"], scope["country_region"]) if part)
    return {**names, "client_name": from_scope or names["client_name"]}


def _carrier_named(text: str) -> str:
    """The canonical carrier whose longest alias appears in ``text``, or "".

    Longest wins so the most specific name decides: "Zurich UK" over "Zurich".
    """
    best_alias, best_canonical = "", ""
    for alias, canonical in settings.carrier_alias_index.items():
        if len(alias) > len(best_alias) and re.search(
            r"\b" + re.escape(alias) + r"\b", text, re.I
        ):
            best_alias, best_canonical = alias, canonical
    return best_canonical


def _first_named(text: str, names: List[str]) -> str:
    """The first of ``names`` that appears in ``text`` as a whole word, or ""."""
    for name in names:
        if re.search(r"\b" + re.escape(name) + r"\b", text, re.I):
            return name
    return ""


def _placeholder_index(shape) -> int | None:
    """A shape's placeholder index, or None when it is not a placeholder."""
    try:
        placeholder = shape.placeholder_format
        return None if placeholder is None else placeholder.idx
    except (AttributeError, ValueError):
        return None
