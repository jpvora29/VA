"""Slot detection — find the fillable units in an analyzed ``Template``.

A *slot* is one place a value goes: a paragraph, a table cell, or a chart's data.
Detection is generic (token-shape based), so it works on any template:

  * digit placeholders — ``xx.x``, ``x.x%``, ``$xx,xxxm``, ``$xxx.xM``, ``x.xB``,
    ``xxxM``, a bare ``x`` (rank) — the author's "fill me" marks;
  * ellipsis prose — ``…`` / ``………`` / ``...`` — qualitative "fill me" marks;
  * enumerated entity labels — ``Country (1)``, ``Region (2)``, ``Carrier``;
  * scatter / bubble charts — a data slot for the whole series.

Each slot carries a ``value_kind`` inferred from the token shape and a ``context``
string (sibling labels / table header / slide title) that ``roles`` uses to map it
to a data role. Real example numbers (``$2,100M`` think-cell axis labels) are NOT
slots — only ``x``-placeholders, ellipses and enumerated labels are.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from studio.template_fill.analyze import Shape, Slide, Template

# A digit-placeholder token: optional $, runs of x/X grouped by . or , optional
# scale suffix (M/B/K/m/b/k) and/or %. Examples: x, xx.x, x.x%, $xx,xxxm, $xxx.xM, x.xB.
_PLACEHOLDER_NUM = re.compile(
    r"(?<![A-Za-z$])\$?[xX]+(?:[.,][xX]+)*(?:[MBKmbk])?%?(?![A-Za-z])"
)
_ELLIPSIS = re.compile(r"(?:…+|\.{3,})")
# An enumerated entity label is the WHOLE string — "Country (1)", "Region (2)", or
# a bare "Carrier"/"Carrier:" title slot. It must full-match so a phrase that merely
# contains those words (e.g. "Carrier's overall rank") is NOT mistaken for a slot.
_ENUM_LABEL = re.compile(r"(?:Country|Region)\s*\(\s*\d+\s*\)|Carrier\s*:?", re.I)
_HAS_X = re.compile(r"[xX]")


@dataclass
class Slot:
    slide_idx: int
    shape_id: int
    where: List[Any]            # ['para', i] | ['cell', r, c] | ['chart']
    token: str                  # the placeholder text actually found
    value_kind: str             # money | pct | int | rank | text | series
    context: str = ""           # sibling labels / header / slide title

    @property
    def key(self) -> str:
        return f"{self.slide_idx}:{self.shape_id}:{'-'.join(str(p) for p in self.where)}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_idx": self.slide_idx,
            "shape_id": self.shape_id,
            "where": list(self.where),
            "token": self.token,
            "value_kind": self.value_kind,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Slot":
        return cls(
            slide_idx=int(d["slide_idx"]),
            shape_id=int(d["shape_id"]),
            where=list(d["where"]),
            token=str(d.get("token", "")),
            value_kind=str(d.get("value_kind", "text")),
            context=str(d.get("context", "")),
        )


def _num_kind(token: str, context: str) -> str:
    """Refine a numeric placeholder into money | pct | rank | int by its shape."""
    t = token.strip()
    if "%" in t:
        return "pct"
    if "$" in t or re.search(r"[MBKmbk]\b|[MBKmbk]$", t):
        return "money"
    ctx = context.lower()
    if "rank" in ctx:
        return "rank"
    # A short bare placeholder (just x / xx) with no scale → an integer (often rank).
    return "int"


def classify(text: str, context: str = "") -> Optional[str]:
    """Value-kind of a placeholder ``text``, or ``None`` if it is not a slot."""
    s = (text or "").strip()
    if not s:
        return None
    if _ENUM_LABEL.fullmatch(s):
        return "text"
    # A numeric digit-placeholder must contain an x AND match the numeric shape.
    if _HAS_X.search(s):
        m = _PLACEHOLDER_NUM.search(s)
        if m and _HAS_X.search(m.group(0)):
            return _num_kind(m.group(0), context)
    if _ELLIPSIS.search(s):
        return "text"
    return None


def _para_context(shape: Shape, para_idx: int, slide_title: str) -> str:
    """Sibling (non-slot) paragraphs in the same shape + the slide title."""
    sibs = [p for i, p in enumerate(shape.paragraphs)
            if i != para_idx and p.strip() and classify(p) is None]
    parts = [p.strip() for p in sibs]
    if slide_title:
        parts.append(slide_title)
    return " · ".join(parts)


def _cell_context(table: List[List[str]], r: int, c: int, slide_title: str) -> str:
    """Header cell above + row label left + slide title — the cell's meaning."""
    parts: List[str] = []
    if table and table[0] and c < len(table[0]) and classify(table[0][c]) is None:
        parts.append(table[0][c].strip())
    if c > 0 and classify(table[r][0]) is None and table[r][0].strip():
        parts.append(table[r][0].strip())
    if slide_title:
        parts.append(slide_title)
    return " · ".join(p for p in parts if p)


_SCATTER_BUBBLE = ("XY_SCATTER", "BUBBLE")


def _shape_center(sh: Shape):
    return (sh.x + sh.w / 2.0, sh.y + sh.h / 2.0)


def _nearby_labels(slide: Slide, shape: Shape, threshold: float) -> str:
    """Text of non-slot label shapes geometrically near ``shape`` (e.g. a value box
    and its caption sitting side by side inside a group)."""
    cx, cy = _shape_center(shape)
    out: List[str] = []
    for other in slide.shapes:
        if other.shape_id == shape.shape_id or other.kind != "text":
            continue
        label = " ".join(p.strip() for p in other.paragraphs
                         if p.strip() and classify(p) is None)
        if not label:
            continue
        ox, oy = _shape_center(other)
        if abs(ox - cx) <= threshold and abs(oy - cy) <= threshold:
            out.append(label)
    return " · ".join(out)


def _detect_slide(slide: Slide, threshold: float) -> List[Slot]:
    title = slide.title()
    out: List[Slot] = []
    for sh in slide.shapes:
        if sh.kind == "text":
            for i, para in enumerate(sh.paragraphs):
                kind = classify(para, title)
                if kind:
                    ctx = _para_context(sh, i, title)
                    near = _nearby_labels(slide, sh, threshold)
                    if near:
                        ctx = f"{ctx} · {near}" if ctx else near
                    out.append(Slot(slide.index, sh.shape_id, ["para", i], para.strip(),
                                    kind, ctx))
        elif sh.kind == "table" and sh.table:
            for r, row in enumerate(sh.table):
                for c, cell in enumerate(row):
                    kind = classify(cell, _cell_context(sh.table, r, c, title))
                    if kind:
                        out.append(Slot(slide.index, sh.shape_id, ["cell", r, c], cell.strip(),
                                        kind, _cell_context(sh.table, r, c, title)))
        elif sh.kind == "chart" and any(k in (sh.chart_type or "") for k in _SCATTER_BUBBLE):
            out.append(Slot(slide.index, sh.shape_id, ["chart"], sh.chart_type or "",
                            "series", title))
    return out


def detect(template: Template) -> List[Slot]:
    """All fillable slots across the template, in reading order."""
    threshold = (template.width_emu or 12192000) * 0.10   # ~1.2in proximity window
    slots: List[Slot] = []
    for slide in template.slides:
        slots.extend(_detect_slide(slide, threshold))
    return slots
