"""Export a `DeckSpec` to a native, editable .pptx — optionally following a template.

Baseline strategy (robust across any template): open the template so the deck
inherits its theme (master background, colours, fonts), then lay each slide's
typed blocks out as real PowerPoint objects (text, native charts, tables) on a
blank layout. With no template, a clean 16:9 brand deck is produced.

Everything is editable in PowerPoint (no screenshots). Charts are native and built
from the same numbers shown on screen, so the export never diverges from the deck.

Incremental complex-template support lives in `template.py` (placeholder discovery
+ `LayoutMap`); this module already honours the template's theme and slide size.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from logger import get_logger
from studio.deck.model import DeckSpec, SlideSpec
from studio.export.template import TemplateProfile
from studio.page.format import money, pct
from ui.color_pallet import ColorPalette

logger = get_logger(__name__)

_EMU_PER_IN = 914_400
_MARGIN = 0.55
_HEADER_H = 1.15
_FOOTER_H = 0.4
FONT = "Arial"


def _rgb(hexstr: str) -> RGBColor:
    return RGBColor.from_string(hexstr.lstrip("#"))


def _slide_dims(prof: TemplateProfile) -> Tuple[float, float]:
    return prof.width_emu / _EMU_PER_IN, prof.height_emu / _EMU_PER_IN


def _text(
    slide, x, y, w, h, text, *, size=12, bold=False, color="1C2636", align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP, spacing=None,
):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = FONT
    run.font.color.rgb = _rgb(color)
    if spacing:
        p.line_spacing = spacing
    return tb


def _rect(slide, x, y, w, h, fill_hex, *, line_hex=None, radius=True):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(fill_hex)
    if line_hex:
        shape.line.color.rgb = _rgb(line_hex)
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


# ── block renderers (region = x, y, w, h in inches) ──────────────────────────


def _kpis(slide, region, items, prof):
    x, y, w, h = region
    cols = 2
    gap = 0.18
    cw = (w - gap) / cols
    ch = 0.92
    for i, k in enumerate(items[:4]):
        cx = x + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (ch + gap)
        _rect(slide, cx, cy, cw, ch, "FFFFFF", line_hex=prof.colors["line"])
        _text(slide, cx + 0.18, cy + 0.12, cw - 0.3, 0.3, str(k["label"]).upper(),
              size=8, bold=True, color=prof.colors["muted"])
        _text(slide, cx + 0.18, cy + 0.34, cw - 0.3, 0.4, str(k["value"]),
              size=17, bold=True, color=prof.colors["navy"])
        if k.get("delta"):
            tone = {"good": "good", "danger": "danger", "warn": "warn"}.get(k.get("tone"), "muted")
            _text(slide, cx + 0.18, cy + 0.7, cw - 0.3, 0.22, str(k["delta"]),
                  size=8.5, bold=True, color=prof.colors[tone])


def _commentary(slide, region, block, prof):
    x, y, w, h = region
    _rect(slide, x, y, w, h, "F7F9FD", line_hex=prof.colors["line"])
    _rect(slide, x, y, 0.07, h, prof.colors["blue"], radius=False)
    pad = 0.22
    _text(slide, x + pad, y + 0.16, w - 2 * pad, 0.3, "EXECUTIVE COMMENTARY",
          size=10, bold=True, color=prof.colors["navy"])
    _text(slide, x + pad, y + 0.5, w - 2 * pad, 0.9, block.headline,
          size=12, bold=True, color=prof.colors["ink"], spacing=1.1)
    cy = y + 1.5
    for pt in list(block.points)[:4]:
        tone = {"good": "good", "danger": "danger", "warn": "warn"}.get(pt.get("tone"), "blue")
        _rect(slide, x + pad, cy + 0.07, 0.1, 0.1, prof.colors[tone], radius=False)
        label = (pt.get("label") or "").strip()
        text = (label + " " if label else "") + pt.get("text", "")
        _text(slide, x + pad + 0.22, cy, w - 2 * pad - 0.22, 0.5, text,
              size=10, color=prof.colors["ink"], spacing=1.05)
        cy += 0.52
    if block.actions:
        cy += 0.05
        _text(slide, x + pad, cy, w - 2 * pad, 0.25, "RECOMMENDED ACTIONS",
              size=9, bold=True, color=prof.colors["navy"])
        cy += 0.3
        for a in list(block.actions)[:3]:
            _text(slide, x + pad, cy, w - 2 * pad, 0.4, "•  " + a, size=9.5, color=prof.colors["ink"])
            cy += 0.34


def _bar(slide, region, block, prof):
    x, y, w, h = region
    data = CategoryChartData()
    data.categories = list(block.labels)
    data.add_series("Premium", list(block.values))
    gf = slide.shapes.add_chart(
        XL_CHART_TYPE.BAR_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), data
    )
    chart = gf.chart
    chart.has_legend = False
    chart.has_title = False
    plot = chart.plots[0]
    plot.gap_width = 60
    series = plot.series[0]
    pts = list(series.points)
    ramp = ColorPalette.sequential(len(pts)) or ["#0B4BFF"]
    for i, point in enumerate(pts):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = _rgb(ramp[i % len(ramp)])
    for ax in (chart.category_axis, chart.value_axis):
        ax.tick_labels.font.size = Pt(9)
        ax.tick_labels.font.name = FONT


def _donut(slide, region, block, prof):
    x, y, w, h = region
    data = CategoryChartData()
    data.categories = list(block.labels)
    data.add_series("Share", list(block.values))
    gf = slide.shapes.add_chart(
        XL_CHART_TYPE.DOUGHNUT, Inches(x), Inches(y), Inches(w), Inches(h), data
    )
    chart = gf.chart
    chart.has_title = False
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.RIGHT
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(9)
    pts = list(chart.plots[0].series[0].points)
    ramp = ColorPalette.sequential(len(pts)) or ["#0B4BFF"]
    for i, point in enumerate(pts):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = _rgb(ramp[i % len(ramp)])


def _fmt_cell(value, kind):
    if value is None or value == "":
        return "—"
    if kind == "money":
        return money(value)
    if kind == "pct":
        return pct(value)
    if kind in ("delta", "pct_signed"):
        return pct(value, signed=True)
    return str(value)


def _table(slide, region, block, prof):
    x, y, w, h = region
    cols = list(block.columns)
    rows = list(block.rows)
    n = len(rows) + 1
    gf = slide.shapes.add_table(n, len(cols), Inches(x), Inches(y), Inches(w), Inches(min(h, 0.34 * n)))
    table = gf.table
    for j, c in enumerate(cols):
        cell = table.cell(0, j)
        cell.text = c["label"]
        para = cell.text_frame.paragraphs[0]
        para.font.size = Pt(9)
        para.font.bold = True
        para.font.name = FONT
        para.font.color.rgb = _rgb(prof.colors["muted"])
        if c.get("align") == "right":
            para.alignment = PP_ALIGN.RIGHT
    for i, row in enumerate(rows, start=1):
        for j, c in enumerate(cols):
            cell = table.cell(i, j)
            cell.text = _fmt_cell(row.get(c["key"]), c.get("kind", "text"))
            para = cell.text_frame.paragraphs[0]
            para.font.size = Pt(9)
            para.font.name = FONT
            para.font.color.rgb = _rgb(prof.colors["ink"])
            if c.get("align") == "right":
                para.alignment = PP_ALIGN.RIGHT


def _callout(slide, region, block, prof):
    x, y, w, h = region
    tone = "warn" if block.tone == "warn" else "blue"
    _rect(slide, x, y, w, h, "F7F9FD", line_hex=prof.colors["line"])
    _rect(slide, x, y, 0.07, h, prof.colors[tone], radius=False)
    _text(slide, x + 0.22, y + 0.1, w - 0.4, h - 0.2, block.text,
          size=12, bold=True, color=prof.colors["navy"], anchor=MSO_ANCHOR.MIDDLE)


def _rail(slide, region, takeaways, prof, *, heading="KEY TAKEAWAYS"):
    """Left commentary rail: heading + tone-dotted bullets."""
    x, y, w, h = region
    _rect(slide, x, y, w, h, "F6F9FF", line_hex=prof.colors["line"])
    pad = 0.2
    _text(slide, x + pad, y + 0.16, w - 2 * pad, 0.3, heading, size=10, bold=True, color=prof.colors["navy"])
    cy = y + 0.6
    for pt in list(takeaways)[:4]:
        tone = {"good": "good", "danger": "danger", "warn": "warn"}.get(pt.get("tone"), "blue")
        _rect(slide, x + pad, cy + 0.06, 0.09, 0.09, prof.colors[tone], radius=False)
        label = (pt.get("label") or "").strip()
        text = (label + " " if label else "") + pt.get("text", "")
        _text(slide, x + pad + 0.2, cy - 0.04, w - 2 * pad - 0.2, 0.7, text,
              size=10, color=prof.colors["ink"], spacing=1.05)
        cy += 0.72


def _stat_band(slide, region, items, prof):
    x, y, w, h = region
    _rect(slide, x, y, w, h, "FFFFFF", line_hex=prof.colors["line"])
    cw = w / max(len(items), 1)
    for i, k in enumerate(items):
        cx = x + i * cw
        if i:
            ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(cx), Inches(y + 0.15), Inches(0.012), Inches(h - 0.3))
            ln.fill.solid(); ln.fill.fore_color.rgb = _rgb(prof.colors["line"]); ln.line.fill.background()
        _text(slide, cx + 0.18, y + 0.16, cw - 0.3, 0.25, str(k["label"]).upper(), size=8.5, bold=True, color=prof.colors["muted"])
        _text(slide, cx + 0.18, y + 0.42, cw - 0.3, 0.5, str(k["value"]), size=22, bold=True, color=prof.colors["navy"])
        if k.get("delta"):
            tone = {"good": "good", "danger": "danger", "warn": "warn"}.get(k.get("tone"), "muted")
            _text(slide, cx + 0.18, y + h - 0.32, cw - 0.3, 0.25, str(k["delta"]), size=9, bold=True, color=prof.colors[tone])


def _swot(slide, region, block, prof):
    x, y, w, h = region
    gap = 0.25
    cw = (w - gap) / 2
    ch = (h - gap) / 2
    quad = [
        ("strengths", "STRENGTHS", "good"), ("weaknesses", "WEAKNESSES", "danger"),
        ("opportunities", "OPPORTUNITIES", "blue"), ("threats", "THREATS", "warn"),
    ]
    for i, (key, label, tone) in enumerate(quad):
        cx = x + (i % 2) * (cw + gap)
        cy = y + (i // 2) * (ch + gap)
        _rect(slide, cx, cy, cw, ch, "FFFFFF", line_hex=prof.colors["line"])
        _rect(slide, cx, cy, cw, 0.06, prof.colors[tone], radius=False)
        _text(slide, cx + 0.18, cy + 0.14, cw - 0.3, 0.28, label, size=11, bold=True, color=prof.colors[tone])
        ty = cy + 0.5
        for b in (getattr(block, key, []) or [])[:4]:
            _text(slide, cx + 0.22, ty, cw - 0.4, 0.4, "•  " + b, size=9.5, color=prof.colors["ink"], spacing=1.0)
            ty += 0.34


def _cards(slide, region, block, prof):
    x, y, w, h = region
    cards = list(block.cards)[:3]
    gap = 0.3
    cw = (w - gap * (len(cards) - 1)) / max(len(cards), 1)
    ch = min(h, 2.6)
    cy = y + (h - ch) / 2
    for i, c in enumerate(cards):
        cx = x + i * (cw + gap)
        tone = {"good": "good", "danger": "danger", "warn": "warn"}.get(c.get("tone"), "blue")
        _rect(slide, cx, cy, cw, ch, "FFFFFF", line_hex=prof.colors["line"])
        _rect(slide, cx, cy, cw, 0.07, prof.colors[tone], radius=False)
        _text(slide, cx + 0.2, cy + 0.22, cw - 0.4, 0.25, c.get("tag", ""), size=9, bold=True, color=prof.colors[tone])
        _text(slide, cx + 0.2, cy + 0.55, cw - 0.4, 0.5, c.get("title", ""), size=15, bold=True, color=prof.colors["navy"])
        _text(slide, cx + 0.2, cy + 1.1, cw - 0.4, ch - 1.2, c.get("body", ""), size=10.5, color=prof.colors["muted"], spacing=1.1)


def _visual(slide, region, block, prof):
    if block.kind == "chart":
        (_donut if block.chart == "donut" else _bar)(slide, region, block, prof)
    elif block.kind == "table":
        _table(slide, region, block, prof)


# ── slide assembly ────────────────────────────────────────────────────────────


def _add_slide(prs, prof, spec: SlideSpec, idx: int, total: int):
    blank = prof.layout_for("blank")
    layout = prs.slide_layouts[blank if blank is not None else len(prs.slide_layouts) - 1]
    slide = prs.slides.add_slide(layout)
    sw, sh = _slide_dims(prof)

    if spec.layout == "cover":
        _rect(slide, 0, 0, sw, sh, prof.colors["navy"], radius=False)
        _text(slide, 1.0, sh / 2 - 1.5, sw - 2, 0.4, spec.eyebrow, size=13, bold=True, color="5CC8FF")
        _text(slide, 1.0, sh / 2 - 1.05, sw - 2, 1.2, spec.title, size=40, bold=True, color="FFFFFF")
        _text(slide, 1.0, sh / 2 + 0.25, sw - 2, 0.5, spec.subtitle, size=16, color="9FC3E8")
        _footer(slide, prof, idx, dark=True)
        return

    # Header: eyebrow (+ question) + action title + accent rule.
    eyebrow = spec.eyebrow + (f"   ·   Q: {spec.question}" if spec.question else "")
    _text(slide, _MARGIN, 0.4, sw - 2 * _MARGIN, 0.28, eyebrow, size=10.5, bold=True, color=prof.colors["blue"])
    _text(slide, _MARGIN, 0.66, sw - 2 * _MARGIN, 0.7, spec.title, size=22, bold=True, color=prof.colors["navy"])
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(_MARGIN), Inches(1.42), Inches(1.0), Inches(0.04))
    rule.fill.solid(); rule.fill.fore_color.rgb = _rgb(prof.colors["blue"]); rule.line.fill.background()

    cx, cy = _MARGIN, 1.7
    cw, ch = sw - 2 * _MARGIN, sh - 1.7 - _FOOTER_H - 0.25
    has_reco = bool(spec.recommendation)
    if has_reco:
        ch -= 0.75  # leave room for the recommendation strip
    blocks = list(spec.blocks)

    if spec.layout == "swot" and blocks:
        _swot(slide, (cx, cy, cw, ch), blocks[0], prof)
    elif spec.layout == "initiatives" and blocks:
        _cards(slide, (cx, cy, cw, ch), blocks[0], prof)
    elif spec.layout == "methodology":
        _methodology(slide, (cx, cy, cw, ch), spec, prof)
    elif spec.layout == "exec":
        kpis = next((b for b in blocks if b.kind == "kpis"), None)
        cards = next((b for b in blocks if b.kind == "cards"), None)
        if kpis:
            _stat_band(slide, (cx, cy, cw, 1.3), kpis.items, prof)
        low_y = cy + 1.55
        low_h = ch - 1.55
        gap = 0.3
        railw = (cw - gap) * 0.55
        _rail(slide, (cx, low_y, railw, low_h), spec.takeaways, prof, heading="WHAT IT MEANS")
        if cards:
            ax = cx + railw + gap
            _rect(slide, ax, low_y, cw - railw - gap, low_h, "F7F9FD", line_hex=prof.colors["line"])
            _text(slide, ax + 0.2, low_y + 0.16, cw - railw - gap - 0.4, 0.3, "PRIORITY ACTIONS", size=10, bold=True, color=prof.colors["navy"])
            ty = low_y + 0.55
            for c in cards.cards[:3]:
                _text(slide, ax + 0.2, ty, cw - railw - gap - 0.4, 0.5, "•  " + c.get("title", ""), size=10.5, color=prof.colors["ink"], spacing=1.05)
                ty += 0.5
    else:
        # insight / decision: left rail + right visual
        gap = 0.35
        railw = (cw - gap) * 0.42
        _rail(slide, (cx, cy, railw, ch), spec.takeaways, prof)
        if blocks:
            _visual(slide, (cx + railw + gap, cy, cw - railw - gap, ch), blocks[0], prof)

    if has_reco:
        _reco_strip(slide, (cx, cy + ch + 0.18, cw, 0.55), spec, prof)
    _footer(slide, prof, idx)


def _reco_strip(slide, region, spec, prof):
    x, y, w, h = region
    _rect(slide, x, y, w, h, "EEF3FF", line_hex=prof.colors["line"])
    _rect(slide, x, y, 0.06, h, prof.colors["blue"], radius=False)
    meta = []
    if spec.owner:
        meta.append(spec.owner)
    if spec.due_date:
        meta.append(spec.due_date)
    if spec.confidence:
        meta.append(f"{spec.confidence} confidence")
    _text(slide, x + 0.2, y + 0.06, w * 0.66, h - 0.12, f"RECOMMENDATION   {spec.recommendation}",
          size=10.5, bold=True, color=prof.colors["navy"], anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, x + w * 0.67, y + 0.06, w * 0.32 - 0.2, h - 0.12, "   ·   ".join(meta),
          size=9.5, color=prof.colors["muted"], align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)


def _methodology(slide, region, spec, prof):
    x, y, w, h = region
    gaps = list(spec.takeaways)
    half = (len(gaps) + 1) // 2
    colw = (w - 0.4) / 2
    for ci, col in enumerate((gaps[:half], gaps[half:])):
        gx = x + ci * (colw + 0.4)
        gy = y
        for g in col:
            _rect(slide, gx, gy, 0.05, 0.5, prof.colors["warn"], radius=False)
            _text(slide, gx + 0.15, gy, colw - 0.2, 0.25, g.get("label", ""), size=11, bold=True, color=prof.colors["navy"])
            _text(slide, gx + 0.15, gy + 0.24, colw - 0.2, 0.6, g.get("text", ""), size=9.5, color=prof.colors["muted"], spacing=1.05)
            gy += 0.78


def _footer(slide, prof, idx, *, dark=False):
    sw, sh = _slide_dims(prof)
    color = "FFFFFF" if dark else prof.colors["muted"]
    _text(slide, _MARGIN, sh - 0.42, 4, 0.25, "Marsh ICG", size=9, bold=True, color=color)
    _text(slide, sw / 2 - 2.5, sh - 0.42, 5, 0.25, "Strictly Private & Confidential  ·  Source: GPR, Carrier Survey",
          size=8, color=color, align=PP_ALIGN.CENTER)
    _text(slide, sw - _MARGIN - 1, sh - 0.42, 1, 0.25, str(idx),
          size=10, bold=True, color=color, align=PP_ALIGN.RIGHT)


def export_deck(
    deck: DeckSpec, *, template_path: Optional[str] = None, out_path: Optional[str] = None
) -> str:
    """Write `deck` to a .pptx (following `template_path`'s theme if given). Returns the path."""
    prof = TemplateProfile.load(template_path)
    prs = Presentation(template_path) if template_path and Path(template_path).exists() else Presentation()
    prs.slide_width = Emu(prof.width_emu)
    prs.slide_height = Emu(prof.height_emu)

    total = len(deck.slides)
    for i, spec in enumerate(deck.slides, start=1):
        _add_slide(prs, prof, spec, i, total)

    if not out_path:
        title = (deck.meta.get("title") or "qbr").replace(" ", "_").replace("—", "-")
        out_path = str(Path.cwd() / f"{title}.pptx")
    prs.save(out_path)
    logger.info("studio: exported deck -> %s", out_path)
    return out_path
