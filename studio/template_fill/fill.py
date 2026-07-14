"""Fill engine — clone the active ``.pptx`` and write the resolved values in.

Generic over any template. Opens the template (so think-cell OLE objects, freeform
shapes, theme, masters and layouts are preserved), then writes each *filled* slot.

Correctness rules (a corrupt deck is worse than an unfilled one):
  * text is written **without deleting run elements** — set the first run's text and
    blank the rest, so think-cell field references and run formatting survive;
  * charts are **never** rewritten (think-cell / externally-linked workbooks corrupt
    on ``replace_data``) — they keep the template's authored data;
  * a final literal-substitution pass fills label tokens like ``Country (1)`` and
    ``xyz`` from the selection;
  * hidden / reordered slides are applied last by editing the slide-id list — so an
    unselected second country/product block is dropped cleanly.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from logger import get_logger
from studio.template_fill.model import materialize_fields

logger = get_logger(__name__)


# ── shape lookup (recursive, by stable cNvPr id) ─────────────────────────────


def _iter_leaves(shapes) -> Iterable[Any]:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for sh in shapes:
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_leaves(sh.shapes)
        else:
            yield sh


def _index_by_id(slide) -> Dict[int, Any]:
    return {int(sh.shape_id): sh for sh in _iter_leaves(slide.shapes)}


# ── run-preserving text writes (never delete <a:r> elements) ─────────────────


def _set_paragraph_text(paragraph, text: str) -> None:
    runs = list(paragraph.runs)
    if runs:
        runs[0].text = text
        for r in runs[1:]:
            r.text = ""
    else:
        paragraph.text = text


def _set_cell_text(cell, text: str) -> None:
    """Write ``text`` into a cell, mapping ``\\n``-separated lines onto the cell's own
    paragraphs — so a composite value keeps its caption paragraph's formatting (e.g.
    ``"$57M (+4.1%▲)\\nMarsh GWP"`` fills the value line and rewrites the 9pt caption
    in place). Surplus template paragraphs are blanked; surplus lines are appended."""
    tf = cell.text_frame
    paras = list(tf.paragraphs)
    lines = str(text).split("\n")
    for i, line in enumerate(lines):
        if i < len(paras):
            _set_paragraph_text(paras[i], line)
        else:
            tf.add_paragraph().text = line
    for p in paras[len(lines):]:
        for r in p.runs:
            r.text = ""


def _write_text_shape(shape, where: List[Any], text: str) -> None:
    if not shape.has_text_frame or not (where and where[0] == "para"):
        return
    idx = int(where[1])
    paras = shape.text_frame.paragraphs
    if 0 <= idx < len(paras):
        _set_paragraph_text(paras[idx], text)


def _write_table(shape, where: List[Any], text: str) -> None:
    if not shape.has_table or not (where and where[0] == "cell"):
        return
    r, c = int(where[1]), int(where[2])
    rows = shape.table.rows
    if 0 <= r < len(rows):
        cells = rows[r].cells
        if 0 <= c < len(cells):
            _set_cell_text(cells[c], text)


# ── commentary typography ─────────────────────────────────────────────────────

# Written commentary uses ONE face/size everywhere. The template's ellipsis
# placeholders carry whatever ad-hoc run formatting the author left (10pt here,
# 14pt there, theme default on appended paragraphs), so inheriting it makes the
# prose inconsistent — too big in one box (overlapping the lines below), too
# small in the next. Roles prefixed ``note:`` (prose slots) and ``fbnote:``
# (feedback/quadrant/highlights table cells) are restyled after the write.
_COMMENTARY_FONT_NAME = "Arial"
_COMMENTARY_FONT_PT = 11
_COMMENTARY_ROLE_PREFIXES = ("note:", "fbnote:")


def _is_commentary_role(role: Optional[str]) -> bool:
    return bool(role) and str(role).startswith(_COMMENTARY_ROLE_PREFIXES)


def _style_commentary_paragraphs(paragraphs) -> None:
    from pptx.util import Pt

    for p in paragraphs:
        for r in p.runs:
            r.font.name = _COMMENTARY_FONT_NAME
            r.font.size = Pt(_COMMENTARY_FONT_PT)


def _style_commentary(shape, where: List[Any]) -> None:
    """Force the standard commentary font on the paragraphs a write just touched."""
    try:
        if where and where[0] == "para" and shape.has_text_frame:
            idx = int(where[1])
            paras = shape.text_frame.paragraphs
            if 0 <= idx < len(paras):
                _style_commentary_paragraphs([paras[idx]])
        elif where and where[0] == "cell" and shape.has_table:
            r, c = int(where[1]), int(where[2])
            rows = shape.table.rows
            if 0 <= r < len(rows) and 0 <= c < len(rows[r].cells):
                _style_commentary_paragraphs(rows[r].cells[c].text_frame.paragraphs)
    except Exception as exc:  # noqa: BLE001 — styling must never break the fill
        logger.warning("template_fill: commentary styling skipped: %s", exc)


# ── literal label substitution (Country (n) / Region (n) / xyz) ──────────────


def _label_subs(values: Dict[str, Any]) -> List[Any]:
    """Literal placeholder substitutions applied to every run (label text), in order.

    Makes the static template wording follow the selection: ``Country (1)`` /
    ``Country xyz`` → the actual country, bare ``Carrier`` → the carrier name, and a
    year shift so ``2025`` / ``FY 2025`` track the selected reporting year.
    """
    subs: List[Any] = []
    countries = []
    i = 0
    while f"country_name[{i}]" in values:
        countries.append(str(values[f"country_name[{i}]"]))
        i += 1
    # "Country (n)" / "Country / Region(n)" / "Region (n)" → the nth country name.
    for idx, name in enumerate(countries, start=1):
        subs.append((re.compile(rf"\b(?:Country\s*/\s*)?(?:Country|Region)\s*\(\s*{idx}\s*\)", re.I), name))
    # Countries the selection doesn't include → blank, so no "Country (2)" placeholder
    # is left on the quadrant/portfolio/feedback slides.
    for idx in range(len(countries) + 1, 10):
        subs.append((re.compile(rf"\b(?:Country\s*/\s*)?(?:Country|Region)\s*\(\s*{idx}\s*\)", re.I), ""))
    # "Country xyz" / "Region xyz" / bare "xyz" mark the spotlight-YoY callout — name it after
    # the spotlight entity (a significant country, or a product when one country is in scope) so
    # the label agrees with the spotlight value. Falls back to the top country.
    spotlight = str(values.get("spotlight_name", "")).strip() or (countries[0] if countries else "")
    if spotlight:
        subs.append((re.compile(r"\b(?:Country|Region)\s+xyz\b", re.I), spotlight))
        subs.append((re.compile(r"\bxyz\b", re.I), spotlight))

    # Product deck: rewrite the template's authored example products (e.g. "Marine
    # Feedback", "Energy") to the single product this deck is for. Longest names first so a
    # multi-word product isn't half-matched by a shorter one.
    product = str(values.get("product_name", "")).strip()
    if product:
        vocab = [str(p).strip() for p in (values.get("product_vocab") or []) if str(p).strip()]
        for authored in sorted(set(vocab), key=len, reverse=True):
            if authored.casefold() != product.casefold():
                subs.append((re.compile(rf"\b{re.escape(authored)}\b"), product))

    carrier = str(values.get("subject_name", "")).strip()
    if carrier:
        # Carrier / Carrier's / Carriers's (template typo) → the carrier (possessive kept).
        def _carrier(m, _c=carrier):
            return f"{_c}’s" if ("'" in m.group(0) or "’" in m.group(0)) else _c

        subs.append((re.compile(r"\bCarriers?(?:['’]s)?\b"), _carrier))

    ty, py = values.get("template_year"), values.get("period_year")
    if ty and py and int(ty) != int(py):
        delta = int(py) - int(ty)
        subs.append((re.compile(r"\b(20\d{2})\b"), lambda m: str(int(m.group(1)) + delta)))
    return subs


def _apply_subs(slide, subs: List[Any]) -> None:
    """Apply label substitutions at PARAGRAPH granularity — a phrase like
    ``Country xyz`` is usually split across runs, so per-run replacement would leave
    the leading word behind. We rewrite a paragraph only when a sub actually changes
    it, writing into run 0 and blanking the rest (run formatting of run 0 survives)."""
    if not subs:
        return
    for sh in _iter_leaves(slide.shapes):
        frames = []
        if sh.has_text_frame:
            frames.append(sh.text_frame)
        elif sh.has_table:
            frames.extend(cell.text_frame for row in sh.table.rows for cell in row.cells)
        for tf in frames:
            for para in tf.paragraphs:
                original = "".join(r.text for r in para.runs)
                if not original:
                    continue
                new = original
                for pattern, repl in subs:
                    new = pattern.sub(repl, new)
                if new != original:
                    _set_paragraph_text(para, new)


# ── added free elements ──────────────────────────────────────────────────────


def _add_elements(slide, elements: List[Dict[str, Any]], width_emu: int, height_emu: int) -> None:
    from pptx.util import Emu, Pt

    for el in elements or []:
        tb = slide.shapes.add_textbox(Emu(int(el.get("x", 0))), Emu(int(el.get("y", 0))),
                                      Emu(int(el.get("w", width_emu // 4))),
                                      Emu(int(el.get("h", height_emu // 10))))
        tb.text_frame.text = str(el.get("text", ""))
        for p in tb.text_frame.paragraphs:
            for r in p.runs:
                r.font.size = Pt(int(el.get("size", 12)))


# ── charts (guarded, best-effort) ────────────────────────────────────────────


def _chart_is_external(chart) -> bool:
    """True for think-cell / externally-linked charts — never safe to rewrite.

    The link is either an external relationship or a ``<c:externalData>`` element in
    the chart XML (think-cell); treat either as external.
    """
    try:
        return (b"externalData" in chart.part.blob
                or any(getattr(r, "is_external", False) for r in chart.part.rels.values()))
    except Exception:  # noqa: BLE001
        return False


def _detach_external_data(chart) -> bool:
    """Cut a chart loose from its external (think-cell / linked-workbook) data source.

    Removes the ``<c:externalData>`` element and drops its relationship, turning the
    chart into a plain native chart whose cached plot XML remains — after which
    ``replace_data`` is safe (python-pptx creates a fresh embedded workbook).
    Returns True when the chart is (now) safe to rewrite."""
    from pptx.oxml.ns import qn

    try:
        cs = chart._chartSpace
        ext = cs.find(qn("c:externalData"))
        if ext is None:
            return not _chart_is_external(chart)
        rid = ext.get(qn("r:id"))
        cs.remove(ext)
        if rid:
            try:
                chart.part.drop_rel(rid)
            except (KeyError, AttributeError):
                pass
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("template_fill: could not detach external chart data: %s", exc)
        return False


def _bubble_points(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The plottable growth points — both YoY axes known. Axis values are FRACTIONS
    (the template charts carry ``0.0%``-formatted axes), sizes are raw premium."""
    return [p for p in points
            if p.get("carrier_yoy") is not None and p.get("marsh_yoy") is not None]


def _write_bubble_chart(chart, points: List[Dict[str, Any]]) -> None:
    """One series per line of business (x = Marsh YoY, y = carrier YoY, size = carrier
    GWP) so every bubble gets its own colour and legend entry."""
    from pptx.chart.data import BubbleChartData
    from pptx.enum.chart import XL_LEGEND_POSITION

    data = BubbleChartData()
    for p in points:
        ser = data.add_series(str(p.get("lob") or ""))
        ser.add_data_point(p["marsh_yoy"] / 100.0, p["carrier_yoy"] / 100.0,
                           abs(p.get("size") or 0.0) or 1.0)
    chart.replace_data(data)
    try:
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
    except Exception:  # noqa: BLE001 — a legend is nice-to-have, never fatal
        pass


def _blank_stale_point_labels(slide, chart_shape, points: List[Dict[str, Any]]) -> None:
    """Blank the hand-placed point-label textboxes over a refilled bubble chart —
    they were positioned for the template's authored dummy bubbles, and the legend
    now names each bubble instead.

    A stale label is a text *placeholder* whose text matches a plotted name, or a
    short placeholder sitting wholly inside the chart frame (the authored labels for
    lines the data doesn't have). Quadrant captions/speech bubbles are rectangles,
    and the axis captions sit outside the frame — both survive. Labels often hold
    their text in ``<a:fld>`` elements (no runs), so the whole frame is replaced."""
    names = {str(p.get("lob") or "").strip() for p in points if p.get("lob")}

    def _inside(sh) -> bool:
        try:
            return (sh.left >= chart_shape.left and sh.top >= chart_shape.top
                    and sh.left + sh.width <= chart_shape.left + chart_shape.width
                    and sh.top + sh.height <= chart_shape.top + chart_shape.height)
        except TypeError:                       # a shape without geometry → leave it
            return False

    for sh in _iter_leaves(slide.shapes):
        if not getattr(sh, "has_text_frame", False) or sh is chart_shape:
            continue
        txt = sh.text_frame.text.strip()
        if not txt or "placeholder" not in sh.name.lower():
            continue
        if txt in names or (len(txt) <= 30 and _inside(sh)):
            sh.text_frame.text = ""


def _fill_charts(prs, values: Dict[str, Any]) -> None:
    """Best-effort: write the computed carrier-vs-Marsh growth data into the deck's
    scatter/bubble charts. Bubble charts that are think-cell/externally linked are
    first detached from the link (native PowerPoint supports bubble charts, so the
    refilled chart stands alone); externally-linked scatter charts (the LC-ranking
    think-cell visual, whose semantics aren't growth) are left untouched.

    Off-switch: ``STUDIO_FILL_CHARTS=off``. Any per-chart failure is swallowed so a
    chart never breaks the export.
    """
    if os.getenv("STUDIO_FILL_CHARTS", "auto").strip().lower() in {"off", "0", "false", "no"}:
        return
    points = _bubble_points((values.get("growth_bubble") or {}).get("points") or [])
    if not points:
        return
    from pptx.chart.data import XyChartData

    for slide in prs.slides:
        for sh in _iter_leaves(slide.shapes):
            if not getattr(sh, "has_chart", False):
                continue
            chart = sh.chart
            ctype = str(chart.chart_type)
            try:
                if "BUBBLE" in ctype:
                    if not _detach_external_data(chart):
                        continue
                    _write_bubble_chart(chart, points)
                    _blank_stale_point_labels(slide, sh, points)
                elif "SCATTER" in ctype:
                    if _chart_is_external(chart):
                        continue
                    data = XyChartData()
                    ser = data.add_series("Carrier vs Marsh growth")
                    for p in points:
                        ser.add_data_point(p["marsh_yoy"] / 100.0, p["carrier_yoy"] / 100.0)
                    chart.replace_data(data)
            except Exception as exc:  # noqa: BLE001 — a chart must never break the export
                logger.warning("template_fill: chart fill skipped (%s): %s", ctype, exc)


# ── hidden / reordered slides ────────────────────────────────────────────────


def _apply_order(prs, order: List[int], hidden: List[int]) -> None:
    """Drop hidden slides and reorder the rest by editing the slide-id list."""
    keep = [i for i in order if i not in set(hidden)]
    if keep == list(range(len(prs.slides))):
        return
    lst = prs.slides._sldIdLst
    ids = list(lst)
    for sld in ids:
        lst.remove(sld)
    for i in keep:
        if 0 <= i < len(ids):
            lst.append(ids[i])


# ── entry point ──────────────────────────────────────────────────────────────


def fill_template(doc: Dict[str, Any], *, out_path: Optional[str] = None) -> str:
    """Write the filled template to ``out_path`` (default: cwd) and return the path."""
    from pptx import Presentation

    prs = Presentation(doc["template_path"])
    fields = materialize_fields(doc)
    values = doc.get("values", {})
    width_emu = int(getattr(prs, "slide_width", 0) or 0)
    height_emu = int(getattr(prs, "slide_height", 0) or 0)
    subs = _label_subs(values)

    by_slide: Dict[int, List[Dict[str, Any]]] = {}
    for fld in fields.values():
        if fld["filled"]:
            by_slide.setdefault(fld["slide_idx"], []).append(fld)

    for sidx, slide in enumerate(prs.slides):
        index = _index_by_id(slide)
        for fld in by_slide.get(sidx, []):
            shape = index.get(int(fld["shape_id"]))
            if shape is None:
                continue
            where = fld["where"]
            if where and where[0] == "para":
                _write_text_shape(shape, where, str(fld["text"]))
            elif where and where[0] == "cell":
                _write_table(shape, where, str(fld["text"]))
            if _is_commentary_role(fld.get("role")):
                _style_commentary(shape, where)
        _apply_subs(slide, subs)
        _add_elements(slide, doc.get("added", {}).get(str(sidx), []), width_emu, height_emu)

    _fill_charts(prs, values)

    n = len(prs.slides)
    _apply_order(prs, doc.get("order", list(range(n))), doc.get("hidden", []))

    if not out_path:
        out_path = str(Path.cwd() / "qbr_filled.pptx")
    prs.save(out_path)
    logger.info("template_fill: exported -> %s", out_path)
    return out_path
