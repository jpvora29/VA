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
    paras = cell.text_frame.paragraphs
    _set_paragraph_text(paras[0], text)
    for p in paras[1:]:
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
    primary = countries[0] if countries else ""
    if primary:
        # "Country xyz" / "Region xyz" → just the country (no leading "Country").
        subs.append((re.compile(r"\b(?:Country|Region)\s+xyz\b", re.I), primary))
        subs.append((re.compile(r"\bxyz\b", re.I), primary))

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


def _fill_charts(prs, values: Dict[str, Any]) -> None:
    """Best-effort: write the computed carrier-vs-Marsh growth data into NATIVE
    scatter/bubble charts. Externally-linked (think-cell) charts are skipped — they
    corrupt on ``replace_data`` and are surfaced with a manual-fill cue instead.

    Off-switch: ``STUDIO_FILL_CHARTS=off``. Any per-chart failure is swallowed so a
    chart never breaks the export.
    """
    if os.getenv("STUDIO_FILL_CHARTS", "auto").strip().lower() in {"off", "0", "false", "no"}:
        return
    points = (values.get("growth_bubble") or {}).get("points") or []
    if not points:
        return
    from pptx.chart.data import BubbleChartData, XyChartData

    for slide in prs.slides:
        for sh in _iter_leaves(slide.shapes):
            if not getattr(sh, "has_chart", False):
                continue
            chart = sh.chart
            if _chart_is_external(chart):
                continue
            ctype = str(chart.chart_type)
            try:
                if "BUBBLE" in ctype:
                    data = BubbleChartData()
                    ser = data.add_series("Carrier vs Marsh growth")
                    for p in points:
                        ser.add_data_point(p.get("marsh_yoy") or 0.0, p.get("carrier_yoy") or 0.0,
                                           abs(p.get("size") or 0.0) or 1.0)
                    chart.replace_data(data)
                elif "SCATTER" in ctype:
                    data = XyChartData()
                    ser = data.add_series("Carrier vs Marsh growth")
                    for p in points:
                        ser.add_data_point(p.get("marsh_yoy") or 0.0, p.get("carrier_yoy") or 0.0)
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
