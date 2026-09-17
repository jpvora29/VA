"""Editing the delivered deck's own words.

An assembled QBR is a **finished** ``.pptx``: its manifest records only the
placeholder tokens that survived the fill, so there are no slots left to type
into (see ``studio.authoring.generate._assembled_review``). What every slide does
have is shapes with geometry and paragraphs, so a block of text on the delivered
deck is addressed by *where it sits*: ``slide:shape``.

One address holds the whole text box — all of its lines — because that is what an
author edits: they rewrite a sentence, add a bullet, drop one. The lines are
written back into the file at export by
:func:`studio.template_fill.fill.apply_text_overrides`, which keeps each
paragraph's own formatting.

This module is pure: it decides what is addressable, and folds one edit into a
document. It never opens a file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

EDITS_KEY = "text_edits"


@dataclass(frozen=True)
class ShapeAddress:
    """Where one editable text box sits in the delivered deck."""

    slide_idx: int
    shape_id: int

    @property
    def key(self) -> str:
        return f"{self.slide_idx}:{self.shape_id}"


@dataclass(frozen=True)
class EditableText:
    """One text box offered for editing, and the lines to show for it."""

    address: ShapeAddress
    lines: Tuple[str, ...]      # what to show: the retyped lines, else the deck's
    original: Tuple[str, ...]   # what the delivered file says, so a revert is known
    edited: bool

    @property
    def text(self) -> str:
        """The block as one editable string — one line per paragraph."""
        return "\n".join(self.lines)


def parse_address(key: Any) -> Optional[ShapeAddress]:
    """``"3:10"`` → an address; anything else → ``None``."""
    parts = str(key or "").split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return ShapeAddress(int(parts[0]), int(parts[1]))


def to_lines(value: Any) -> Tuple[str, ...]:
    """Split what the edit field holds into paragraphs, dropping empty ones.

    A blank line in a PowerPoint text box is spacing the template owns, not a
    paragraph the author wrote, so it never survives a round-trip.
    """
    return tuple(
        line.strip() for line in str(value or "").splitlines() if line.strip()
    )


def editable_text(
    shape: Any, slide_idx: int, edits: Mapping[str, Sequence[str]]
) -> Optional[EditableText]:
    """The editable block of one shape, or ``None`` when it holds no prose.

    Text shapes only — a chart's data, a table's cells and a picture are not prose.
    """
    if getattr(shape, "kind", "") != "text":
        return None
    original = to_lines("\n".join(getattr(shape, "paragraphs", None) or []))
    if not original:
        return None
    address = ShapeAddress(slide_idx, int(shape.shape_id))
    override = edits.get(address.key)
    return EditableText(
        address=address,
        lines=tuple(str(line) for line in override) if override is not None else original,
        original=original,
        edited=override is not None,
    )


def text_edits(doc: Mapping[str, Any]) -> Dict[str, List[str]]:
    """The retyped text blocks held on a template document, keyed by address."""
    stored = doc.get(EDITS_KEY) or {}
    return {
        str(key): [str(line) for line in value]
        for key, value in stored.items()
        if parse_address(key) and isinstance(value, (list, tuple))
    }


def current_lines(doc: Mapping[str, Any], key: str, original: Sequence[str]) -> List[str]:
    """The lines the edit field is showing: the retyped ones, else the deck's own."""
    stored = text_edits(doc).get(str(key))
    return list(stored) if stored is not None else [str(x) for x in (original or ())]


def _store(
    doc: Mapping[str, Any], key: str, lines: Sequence[str], original: Sequence[str]
) -> Dict[str, Any]:
    """Hold ``lines`` against ``key`` — or drop the override when they are the deck's own.

    One place decides what counts as an edit, so every way of reaching it (retyping a
    line, adding one, deleting one) answers the same question the same way.
    """
    doc = dict(doc)
    if parse_address(key) is None:
        return doc
    kept = [str(line).strip() for line in lines]
    edits = text_edits(doc)
    # A line the author just opened is still a difference from the deck — comparing
    # only the written lines would make "Add line" undo itself on the spot.
    if not any(kept) or tuple(kept) == tuple(original or ()):
        edits.pop(str(key), None)
    else:
        edits[str(key)] = kept
    return {**doc, EDITS_KEY: edits}


def set_text_edit(
    doc: Mapping[str, Any], key: str, value: Any, *, original: Sequence[str]
) -> Dict[str, Any]:
    """Fold a whole retyped text box into the document — one line per paragraph."""
    return _store(doc, key, to_lines(value), original)


def set_line(
    doc: Mapping[str, Any], key: str, index: int, value: Any, *, original: Sequence[str]
) -> Dict[str, Any]:
    """Retype one line of a text box, leaving its neighbours alone."""
    lines = current_lines(doc, key, original)
    if not 0 <= index < len(lines):
        return dict(doc)
    lines[index] = " ".join(str(value or "").split())
    return _store(doc, key, lines, original)


def add_line(doc: Mapping[str, Any], key: str, *, original: Sequence[str]) -> Dict[str, Any]:
    """Open an empty line at the end of a text box for the author to write into."""
    lines = current_lines(doc, key, original)
    if lines and not lines[-1].strip():
        return dict(doc)        # one blank line at a time
    return _store(doc, key, lines + [""], original)


def delete_line(
    doc: Mapping[str, Any], key: str, index: int, *, original: Sequence[str]
) -> Dict[str, Any]:
    """Remove one line from a text box."""
    lines = current_lines(doc, key, original)
    if not 0 <= index < len(lines):
        return dict(doc)
    return _store(doc, key, lines[:index] + lines[index + 1:], original)


def clear_text_edit(doc: Mapping[str, Any], key: str) -> Dict[str, Any]:
    """Put one text box back to what the delivered deck says."""
    edits = text_edits(doc)
    edits.pop(str(key), None)
    return {**dict(doc), EDITS_KEY: edits}


def grouped(edits: Mapping[str, Sequence[str]]) -> Dict[int, Dict[int, List[str]]]:
    """``{slide_idx: {shape_id: [lines]}}`` — the shape the writer walks in.

    A line the author opened but never wrote in is an authoring state, not a blank
    paragraph to push into the deck, so empties are dropped on the way out.
    """
    out: Dict[int, Dict[int, List[str]]] = {}
    for key, lines in edits.items():
        address = parse_address(key)
        if address is None:
            continue
        written = [str(x) for x in lines if str(x).strip()]
        if written:
            out.setdefault(address.slide_idx, {})[address.shape_id] = written
    return out
