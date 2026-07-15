"""TemplateDescriptor — deterministic, JSON-able structure of a ``.pptx``.

The plan's Phase-1 contract (QBR_STUDIO_TEMPLATE_INTELLIGENCE_PLAN.md): slide
count/size, per-slide layout name and title, and per-shape ids, kinds, geometry,
text and placeholder tokens. Produced only by Python/OpenXML logic (never by an
LLM), so the ids downstream binding maps reference are stable across runs.

Pure data + pure helpers — no pptx, no engine, no LLM imports here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def shape_ref(slide_idx: int, shape_id: int) -> str:
    """The stable reference for one shape — the id vocabulary agents must use."""
    return f"s{slide_idx}:sh{shape_id}"


@dataclass(frozen=True)
class ShapeDescriptor:
    """One leaf shape: identity, geometry, kind and its fillable content."""

    shape_id: int                          # cNvPr id — unique within the slide
    name: str
    kind: str                              # text | table | chart | picture | ole | other
    x: int = 0                             # absolute EMU
    y: int = 0
    w: int = 0
    h: int = 0
    paragraphs: Tuple[str, ...] = ()
    table_rows: int = 0
    table_cols: int = 0
    chart_type: Optional[str] = None
    chart_series_names: Tuple[str, ...] = ()
    chart_external: bool = False           # think-cell/linked → manual-fill only
    tokens: Tuple[str, ...] = ()           # placeholder tokens found ("$xx,xxxm", "…")

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shape_id": self.shape_id, "name": self.name, "kind": self.kind,
            "x": self.x, "y": self.y, "w": self.w, "h": self.h,
            "paragraphs": list(self.paragraphs),
            "table_rows": self.table_rows, "table_cols": self.table_cols,
            "chart_type": self.chart_type,
            "chart_series_names": list(self.chart_series_names),
            "chart_external": self.chart_external,
            "tokens": list(self.tokens),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ShapeDescriptor":
        return cls(
            shape_id=int(d["shape_id"]), name=str(d.get("name", "")),
            kind=str(d.get("kind", "other")),
            x=int(d.get("x", 0)), y=int(d.get("y", 0)),
            w=int(d.get("w", 0)), h=int(d.get("h", 0)),
            paragraphs=tuple(d.get("paragraphs", [])),
            table_rows=int(d.get("table_rows", 0)), table_cols=int(d.get("table_cols", 0)),
            chart_type=d.get("chart_type"),
            chart_series_names=tuple(d.get("chart_series_names", [])),
            chart_external=bool(d.get("chart_external", False)),
            tokens=tuple(d.get("tokens", [])),
        )


@dataclass(frozen=True)
class SlideDescriptor:
    index: int
    layout: str
    title: str
    shapes: Tuple[ShapeDescriptor, ...] = ()

    def shape(self, shape_id: int) -> Optional[ShapeDescriptor]:
        return next((s for s in self.shapes if s.shape_id == shape_id), None)

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "layout": self.layout, "title": self.title,
                "shapes": [s.to_dict() for s in self.shapes]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SlideDescriptor":
        return cls(index=int(d["index"]), layout=str(d.get("layout", "")),
                   title=str(d.get("title", "")),
                   shapes=tuple(ShapeDescriptor.from_dict(s) for s in d.get("shapes", [])))


@dataclass(frozen=True)
class TemplateDescriptor:
    """The whole template: identity (path + content fingerprint) and structure."""

    path: str
    fingerprint: str                       # sha1 of the file bytes — change detection
    width_emu: int
    height_emu: int
    slides: Tuple[SlideDescriptor, ...] = ()

    @property
    def slide_count(self) -> int:
        return len(self.slides)

    def slide(self, idx: int) -> Optional[SlideDescriptor]:
        return self.slides[idx] if 0 <= idx < len(self.slides) else None

    def shape(self, slide_idx: int, shape_id: int) -> Optional[ShapeDescriptor]:
        s = self.slide(slide_idx)
        return s.shape(shape_id) if s else None

    def shape_refs(self) -> frozenset:
        """Every valid shape reference — the universe agent output is checked against."""
        return frozenset(
            shape_ref(s.index, sh.shape_id) for s in self.slides for sh in s.shapes
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "fingerprint": self.fingerprint,
                "width_emu": self.width_emu, "height_emu": self.height_emu,
                "slides": [s.to_dict() for s in self.slides]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TemplateDescriptor":
        return cls(path=str(d.get("path", "")), fingerprint=str(d.get("fingerprint", "")),
                   width_emu=int(d.get("width_emu", 0)), height_emu=int(d.get("height_emu", 0)),
                   slides=tuple(SlideDescriptor.from_dict(s) for s in d.get("slides", [])))
