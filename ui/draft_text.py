"""Tidy the half-written answer while it is still streaming.

The live draft is plain text, not markdown: mid-stream, markdown is not yet markdown,
and re-parsing it on every tick made the bubble thrash (see `ui.callbacks._live_draft`).
Plain text is stable, but it leaves the syntax showing — a sentence arrives as
``grew **12.4% year on year`` and a table as a wall of pipes.

So the draft gets one pass of cosmetic softening: drop the emphasis and heading markers
that carry no meaning without their closing half, and render a table row as spaced
cells rather than pipes. Nothing is reordered and no words are removed, so the draft
always reads as the answer being written. The moment the turn commits, the real
markdown renderer takes over and the formatting lands for real.

Pure and import-light on purpose: no Dash, no `core`, so it is unit-testable on its own.
"""
from __future__ import annotations

import re

# Inline emphasis that reads as noise until its closing marker arrives. Table
# pipes are handled separately because they carry column structure worth keeping.
_EMPHASIS = re.compile(r"(\*\*|__|\*|`)")
# A leading heading / quote / bullet marker. The bullet's "- " is kept as "• " so
# a list still reads as a list.
_HEADING = re.compile(r"^\s{0,3}(#{1,6}\s+|>\s?)", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
# A markdown table's separator row: |---|:--:|---| and friends. It is pure
# scaffolding, so it is dropped rather than softened.
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


def _soften_row(line: str) -> str:
    """``| Cyber | $1.8m |`` → ``Cyber   $1.8m`` — the cells, without the scaffolding."""
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return "   ".join(cell for cell in cells if cell)


def draft_text(text: str) -> str:
    """The streamed text, softened for display while it is still being written.

    Only ever removes markup characters, never words, so what the reader sees is a
    faithful prefix of the answer they are about to get.
    """
    if not text:
        return ""
    lines = []
    for line in text.split("\n"):
        if _TABLE_RULE.match(line) and "-" in line:
            continue
        if "|" in line and line.strip().startswith("|"):
            line = _soften_row(line)
        lines.append(line)
    softened = "\n".join(lines)
    softened = _HEADING.sub("", softened)
    softened = _BULLET.sub(r"\1• ", softened)
    return _EMPHASIS.sub("", softened)
