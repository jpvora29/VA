"""Deterministic PPTX → :class:`TemplateDescriptor` (plan Phase 1).

Reuses the proven ``template_fill.analyze`` reader (geometry, groups flattened,
theme, charts) rather than re-implementing OpenXML parsing, then projects the
result onto the pure descriptor contract. Same input file ⇒ byte-identical
descriptor dict, which the stability tests assert.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from studio.template_fill.analyze import Shape, Template, analyze
from studio.template_fill.slots import classify
from studio.template_intelligence.descriptor import (
    ShapeDescriptor,
    SlideDescriptor,
    TemplateDescriptor,
)


def file_fingerprint(path: str) -> str:
    """sha1 of the file bytes — the identity binding maps are pinned to."""
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def _tokens(shape: Shape) -> tuple:
    """The placeholder tokens present in a shape (paragraphs + table cells)."""
    found = []
    for p in shape.paragraphs:
        if p.strip() and classify(p) is not None:
            found.append(p.strip())
    for row in shape.table or []:
        for cell in row:
            if cell.strip() and classify(cell) is not None:
                found.append(cell.strip())
    return tuple(found)


def _shape_descriptor(shape: Shape) -> ShapeDescriptor:
    table = shape.table or []
    return ShapeDescriptor(
        shape_id=shape.shape_id, name=shape.name, kind=shape.kind,
        x=shape.x, y=shape.y, w=shape.w, h=shape.h,
        paragraphs=tuple(shape.paragraphs),
        table_rows=len(table), table_cols=len(table[0]) if table else 0,
        chart_type=shape.chart_type,
        chart_series_names=tuple(name for name, _ in shape.chart_series),
        chart_external=shape.chart_external,
        tokens=_tokens(shape),
    )


def descriptor_from_template(template: Template, *, fingerprint: str = "") -> TemplateDescriptor:
    """Pure projection of an analyzed ``Template`` onto the descriptor contract."""
    slides = tuple(
        SlideDescriptor(
            index=s.index, layout=s.layout, title=s.title(),
            shapes=tuple(_shape_descriptor(sh) for sh in s.shapes),
        )
        for s in template.slides
    )
    return TemplateDescriptor(
        path=template.path, fingerprint=fingerprint,
        width_emu=template.width_emu, height_emu=template.height_emu, slides=slides,
    )


def parse_template(path: str) -> TemplateDescriptor:
    """Introspect ``path`` into a :class:`TemplateDescriptor` (deterministic)."""
    return descriptor_from_template(analyze(str(path)), fingerprint=file_fingerprint(str(path)))
