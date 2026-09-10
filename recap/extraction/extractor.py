"""
extraction/extractor.py

Stage 1 â€” Raw PPT Extraction.

Converts a .pptx file into a RawDeck object: the immutable source-of-truth
representation of every slide, element, table, chart, image, and note.

Nothing here interprets business meaning. Coordinates are preserved in EMU
(English Metric Units, as used by python-pptx). Reading order is derived
from a top-to-bottom, left-to-right spatial sort.

Dependencies: python-pptx
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.util import Emu
from pptx.shapes.base import BaseShape
from pptx.shapes.group import GroupShape
from pptx.shapes.graphfrm import GraphicFrame
from pptx.oxml.ns import qn

from recap.schemas.raw_extraction import (
    ElementType,
    RawChart,
    RawChartSeries,
    RawDeck,
    RawElement,
    RawSlide,
    RawTable,
    RawTableCell,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shape-type mapping
# ---------------------------------------------------------------------------

_MSO_TO_ELEMENT_TYPE: Dict[int, ElementType] = {
    MSO_SHAPE_TYPE.TEXT_BOX:        ElementType.TEXT_BOX,
    MSO_SHAPE_TYPE.TABLE:           ElementType.TABLE,
    MSO_SHAPE_TYPE.CHART:           ElementType.CHART,
    MSO_SHAPE_TYPE.PICTURE:         ElementType.IMAGE,
    MSO_SHAPE_TYPE.GROUP:           ElementType.GROUP,
    MSO_SHAPE_TYPE.AUTO_SHAPE:      ElementType.SHAPE,
    MSO_SHAPE_TYPE.PLACEHOLDER:     ElementType.PLACEHOLDER,
    MSO_SHAPE_TYPE.LINE:            ElementType.CONNECTOR,
    MSO_SHAPE_TYPE.FREEFORM:        ElementType.SHAPE,
    MSO_SHAPE_TYPE.MEDIA:           ElementType.IMAGE,
}


def _element_type_from_shape(shape: BaseShape) -> ElementType:
    try:
        mso = shape.shape_type
        return _MSO_TO_ELEMENT_TYPE.get(int(mso), ElementType.UNKNOWN)
    except Exception:
        return ElementType.UNKNOWN


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_text(shape: BaseShape) -> Optional[str]:
    """Return clean plain text from a shape that has a text frame."""
    try:
        if not shape.has_text_frame:
            return None
        paragraphs = []
        for para in shape.text_frame.paragraphs:
            line = "".join(run.text for run in para.runs).strip()
            if line:
                paragraphs.append(line)
        return "\n".join(paragraphs) if paragraphs else None
    except Exception:
        return None


def _extract_font_info(shape: BaseShape) -> Tuple[Optional[float], Optional[bool], Optional[bool]]:
    """Return (font_size_pt, is_bold, is_italic) from the first run, if available."""
    try:
        if not shape.has_text_frame:
            return None, None, None
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                font = run.font
                size = float(font.size.pt) if font.size else None
                return size, font.bold, font.italic
    except Exception:
        pass
    return None, None, None


def _extract_fill_color(shape: BaseShape) -> Optional[str]:
    """Return hex fill color string if shape has a solid fill, else None."""
    try:
        fill = shape.fill
        if fill.type and fill.fore_color:
            rgb = fill.fore_color.rgb
            return str(rgb)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def _extract_table(shape: BaseShape) -> Optional[RawTable]:
    try:
        if not shape.has_table:
            return None
        tbl = shape.table
        cells: List[RawTableCell] = []
        for ri, row in enumerate(tbl.rows):
            for ci, cell in enumerate(row.cells):
                text = cell.text_frame.text.strip() if cell.text_frame else ""
                cells.append(
                    RawTableCell(
                        row=ri,
                        col=ci,
                        text=text,
                        is_header=(ri == 0),
                        row_span=cell.span_height or 1,
                        col_span=cell.span_width or 1,
                    )
                )
        return RawTable(rows=len(tbl.rows), cols=len(tbl.columns), cells=cells)
    except Exception as exc:
        logger.debug("Table extraction failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Chart extraction
# ---------------------------------------------------------------------------

def _extract_chart_axis_title(chart, axis_type: str) -> Optional[str]:
    """
    Extract axis title text for "category" or "value" axis.
    Returns None if the axis or its title is missing / has no text.
    """
    try:
        from pptx.oxml.ns import qn as _qn
        # chart._element → c:chartSpace → c:chart → c:plotArea
        plot_area = chart._element.find(".//" + _qn("c:plotArea"))
        if plot_area is None:
            return None
        # category axis: c:catAx / c:valAx; value axis: c:valAx
        # We look at catAx for category labels, valAx for value axis label
        ax_tag = _qn("c:catAx") if axis_type == "category" else _qn("c:valAx")
        for ax in plot_area.findall(ax_tag):
            title_el = ax.find(_qn("c:title"))
            if title_el is None:
                continue
            tx = title_el.find(".//" + _qn("c:v"))
            if tx is not None and tx.text:
                return tx.text.strip() or None
            # Try c:t (rich text run)
            t_el = title_el.find(".//" + _qn("a:t"))
            if t_el is not None and t_el.text:
                return t_el.text.strip() or None
    except Exception:
        pass
    return None


def _extract_chart_categories(chart) -> List[str]:
    """
    Extract category (x-axis) labels shared across all series.
    Uses the first series\'s category ref if available.
    """
    cats: List[str] = []
    try:
        from pptx.oxml.ns import qn as _qn
        plot_area = chart._element.find(".//" + _qn("c:plotArea"))
        if plot_area is None:
            return cats
        # Walk every ser element looking for c:cat → c:strRef / c:numRef → c:v
        for ser in plot_area.findall(".//" + _qn("c:ser")):
            cat_el = ser.find(_qn("c:cat"))
            if cat_el is None:
                continue
            vals = cat_el.findall(".//" + _qn("c:v"))
            if vals:
                cats = [v.text.strip() for v in vals if v.text]
                break  # same categories for every series
    except Exception:
        pass
    return cats


def _extract_series_values_xml(chart) -> List[Dict]:
    """
    Extract all series names and their numeric values directly from XML.
    Returns list of {name, values: [float|None]}.
    Also captures data label strings if present.
    """
    from pptx.oxml.ns import qn as _qn
    results = []
    try:
        plot_area = chart._element.find(".//" + _qn("c:plotArea"))
        if plot_area is None:
            return results
        for ser in plot_area.findall(".//" + _qn("c:ser")):
            # Series name
            name: Optional[str] = None
            tx_el = ser.find(_qn("c:tx"))
            if tx_el is not None:
                v_el = tx_el.find(".//" + _qn("c:v"))
                if v_el is not None and v_el.text:
                    name = v_el.text.strip()
                else:
                    t_el = tx_el.find(".//" + _qn("a:t"))
                    if t_el is not None and t_el.text:
                        name = t_el.text.strip()

            # Numeric values (c:val or c:yVal)
            values: List = []
            for val_tag in (_qn("c:val"), _qn("c:yVal")):
                val_el = ser.find(val_tag)
                if val_el is None:
                    continue
                num_ref = val_el.find(_qn("c:numRef"))
                if num_ref is not None:
                    for v in num_ref.findall(".//" + _qn("c:v")):
                        try:
                            values.append(float(v.text))
                        except (TypeError, ValueError):
                            values.append(None)
                break  # only need one val block

            # Data labels (dLbls)
            data_labels: List[str] = []
            dlbls = ser.find(_qn("c:dLbls"))
            if dlbls is not None:
                for dlbl in dlbls.findall(_qn("c:dLbl")):
                    t_el = dlbl.find(".//" + _qn("a:t"))
                    if t_el is not None and t_el.text:
                        data_labels.append(t_el.text.strip())

            results.append({
                "name": name,
                "values": values,
                "data_labels": data_labels,
            })
    except Exception as exc:
        logger.debug("XML series extraction failed: %s", exc)
    return results


def _extract_chart(shape: BaseShape) -> Optional[RawChart]:
    """
    Extract a RawChart with chart title, axis labels, category labels,
    and series values.  Falls back gracefully at every step.
    """
    try:
        if not shape.has_chart:
            return None
        chart = shape.chart

        # ── Chart title ────────────────────────────────────────────
        title: Optional[str] = None
        try:
            if chart.has_title and chart.chart_title.has_text_frame:
                title = chart.chart_title.text_frame.text.strip() or None
        except Exception:
            pass

        # ── Chart type ─────────────────────────────────────────────
        chart_type: Optional[str] = None
        try:
            chart_type = str(chart.chart_type)
        except Exception:
            pass

        # ── Axis titles ────────────────────────────────────────────
        category_axis_label = _extract_chart_axis_title(chart, "category")
        value_axis_label    = _extract_chart_axis_title(chart, "value")

        # ── Shared category labels (x-axis) ────────────────────────
        shared_categories = _extract_chart_categories(chart)

        # ── Series data (XML path — most reliable) ─────────────────
        xml_series = _extract_series_values_xml(chart)

        # ── Build RawChartSeries list ───────────────────────────────
        series_list: List[RawChartSeries] = []

        if xml_series:
            for s in xml_series:
                # Use shared_categories if the series has no per-series cats
                cats = shared_categories if shared_categories else []
                # Fill values — merge data_labels over numeric values where
                # the numeric values are missing/None
                raw_vals = s["values"]
                dl = s["data_labels"]
                merged_vals: List = []
                for i, v in enumerate(raw_vals):
                    if v is not None:
                        merged_vals.append(v)
                    elif i < len(dl):
                        merged_vals.append(dl[i])
                    else:
                        merged_vals.append(None)
                # If no numeric values but data_labels exist, use labels
                if not merged_vals and dl:
                    merged_vals = dl  # type: ignore[assignment]

                series_list.append(RawChartSeries(
                    series_name=s["name"],
                    categories=cats,
                    values=merged_vals,
                ))
        else:
            # Fallback: python-pptx high-level API
            try:
                for series in chart.series:
                    vals: List = []
                    try:
                        vals = [v for v in series.values]
                    except Exception:
                        pass
                    series_list.append(RawChartSeries(
                        series_name=getattr(series, "name", None),
                        categories=shared_categories,
                        values=vals,
                    ))
            except Exception as exc:
                logger.debug("Fallback series extraction failed: %s", exc)

        # ── has_data_labels flag ────────────────────────────────────
        has_dl = any(bool(s.get("data_labels")) for s in xml_series)

        return RawChart(
            chart_type=chart_type,
            title=title,
            series=series_list,
            has_data_labels=has_dl,
            category_axis_label=category_axis_label,
            value_axis_label=value_axis_label,
        )
    except Exception as exc:
        logger.debug("Chart extraction failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Alt-text / image description
# ---------------------------------------------------------------------------

def _extract_alt_text(shape: BaseShape) -> Optional[str]:
    try:
        desc = shape._element.get(qn("p:nvPicPr") + "/" + qn("p:cNvPr") + "[@descr]")
        if desc:
            return desc
        # Try the title attribute on the non-visual properties
        cNvPr = shape._element.find(".//" + qn("p:cNvPr"))
        if cNvPr is not None:
            return cNvPr.get("descr") or cNvPr.get("title") or None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Placeholder type
# ---------------------------------------------------------------------------

def _placeholder_type(shape: BaseShape) -> Optional[str]:
    try:
        ph_type = shape.placeholder_format.type
        return str(ph_type).split(".")[-1]  # e.g. 'TITLE', 'BODY'
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Reading-order sort
# ---------------------------------------------------------------------------

def _assign_reading_order(elements: List[RawElement]) -> None:
    """
    Sort elements top-to-bottom, left-to-right and assign reading_order.
    Elements with no coordinates are placed at the end.
    """
    def sort_key(el: RawElement) -> Tuple:
        y = el.y if el.y is not None else int(1e12)
        x = el.x if el.x is not None else int(1e12)
        return y, x

    sorted_els = sorted(elements, key=sort_key)
    for i, el in enumerate(sorted_els):
        el.reading_order = i


# ---------------------------------------------------------------------------
# Unique element ID generator
# ---------------------------------------------------------------------------

def _make_element_id(deck_id: str, slide_number: int, shape_id: int) -> str:
    return f"{deck_id}_s{slide_number:03d}_shp{shape_id:04d}"


# ---------------------------------------------------------------------------
# Recursive shape extractor (handles groups)
# ---------------------------------------------------------------------------

def _extract_shapes(
    shapes,
    deck_id: str,
    slide_number: int,
    parent_group_id: Optional[str] = None,
    collected: Optional[List[RawElement]] = None,
) -> List[RawElement]:
    """
    Recursively walk shapes (including groups) and produce RawElement list.
    """
    if collected is None:
        collected = []

    for shape in shapes:
        shape_id = shape.shape_id
        elem_id = _make_element_id(deck_id, slide_number, shape_id)
        etype = _element_type_from_shape(shape)

        text = _extract_text(shape)
        alt_text = _extract_alt_text(shape) if etype == ElementType.IMAGE else None
        table = _extract_table(shape) if etype == ElementType.TABLE else None
        chart = _extract_chart(shape) if etype == ElementType.CHART else None
        font_size, is_bold, is_italic = _extract_font_info(shape)
        fill_color = _extract_fill_color(shape)

        is_ph = hasattr(shape, "is_placeholder") and shape.is_placeholder
        ph_type = _placeholder_type(shape) if is_ph else None

        hyperlink: Optional[str] = None
        try:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        hl = run.hyperlink
                        if hl and hl.address:
                            hyperlink = hl.address
                            break
        except Exception:
            pass

        # Child IDs for group shapes
        child_ids: List[str] = []
        if etype == ElementType.GROUP:
            try:
                child_ids = [
                    _make_element_id(deck_id, slide_number, child.shape_id)
                    for child in shape.shapes
                ]
            except Exception:
                pass

        elem = RawElement(
            element_id=elem_id,
            deck_id=deck_id,
            slide_number=slide_number,
            element_type=etype,
            shape_type=str(shape.shape_type) if hasattr(shape, "shape_type") else None,
            text=text,
            alt_text=alt_text,
            table=table,
            chart=chart,
            x=int(shape.left) if shape.left is not None else None,
            y=int(shape.top)  if shape.top  is not None else None,
            width=int(shape.width)  if shape.width  is not None else None,
            height=int(shape.height) if shape.height is not None else None,
            parent_group_id=parent_group_id,
            child_element_ids=child_ids,
            font_size=font_size,
            is_bold=is_bold,
            is_italic=is_italic,
            fill_color=fill_color,
            hyperlink=hyperlink,
            is_placeholder=bool(is_ph),
            placeholder_type=ph_type,
        )
        collected.append(elem)

        # Recurse into group children
        if etype == ElementType.GROUP:
            try:
                _extract_shapes(
                    shape.shapes,
                    deck_id=deck_id,
                    slide_number=slide_number,
                    parent_group_id=elem_id,
                    collected=collected,
                )
            except Exception as exc:
                logger.debug("Group recursion failed for %s: %s", elem_id, exc)

    return collected


# ---------------------------------------------------------------------------
# Section map builder
# ---------------------------------------------------------------------------

def _build_section_map(prs: Presentation) -> Dict[str, List[int]]:
    """
    Extract section names and their slide ranges from the presentation XML.
    Returns {section_name: [slide_numbers]} (1-based).
    """
    section_map: Dict[str, List[int]] = {}
    try:
        sldIdLst = prs.slides._sldIdLst
        # Build slide-id â†’ 1-based index map
        id_to_idx = {
            el.get("id"): i + 1
            for i, el in enumerate(sldIdLst)
        }

        # Walk sectionLst in presentation XML
        prs_el = prs.core_properties._element  # not ideal â€” use prs._element
        prs_el = prs.slides._sldIdLst.getparent().getparent()
        ext_lst = prs_el.find(qn("p:extLst"))
        if ext_lst is None:
            return section_map
        for ext in ext_lst:
            for sec_lst in ext:
                tag = sec_lst.tag.split("}")[-1] if "}" in sec_lst.tag else sec_lst.tag
                if tag == "sectionLst":
                    for section in sec_lst:
                        name = section.get("name", "Unnamed Section")
                        slide_ids = [
                            sldId.get("id")
                            for sldId in section.findall(
                                ".//{http://schemas.microsoft.com/office/powerpoint/2012/main}sldId"
                            )
                        ]
                        slide_numbers = [
                            id_to_idx[sid]
                            for sid in slide_ids
                            if sid in id_to_idx
                        ]
                        if slide_numbers:
                            section_map[name] = slide_numbers
    except Exception as exc:
        logger.debug("Section map extraction failed: %s", exc)
    return section_map


# ---------------------------------------------------------------------------
# Slide title helper
# ---------------------------------------------------------------------------

def _extract_slide_title(slide) -> Optional[str]:
    try:
        return slide.shapes.title.text.strip() or None
    except Exception:
        pass
    # Fallback: look for TITLE placeholder
    try:
        for shape in slide.shapes:
            if shape.is_placeholder:
                ph = shape.placeholder_format
                if ph.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE):
                    txt = shape.text_frame.text.strip()
                    if txt:
                        return txt
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Notes extraction
# ---------------------------------------------------------------------------

def _extract_notes(slide) -> Optional[str]:
    try:
        notes_slide = slide.notes_slide
        tf = notes_slide.notes_text_frame
        text = tf.text.strip() if tf else ""
        return text if text else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main extractor class
# ---------------------------------------------------------------------------

class PPTExtractor:
    """
    Extracts a .pptx file into a RawDeck.

    Usage
    -----
    extractor = PPTExtractor()
    deck = extractor.extract(
        file_path="path/to/deck.pptx",
        deck_id="client_q2_2026",
        meeting_date="2026-04-01",
        quarter="Q2",
        year=2026,
        client_name="Acme Corp",
    )
    """

    def extract(
        self,
        file_path: str | Path,
        deck_id: str,
        meeting_date: Optional[str] = None,
        quarter: Optional[str] = None,
        half_year: Optional[str] = None,
        year: Optional[int] = None,
        period_label: Optional[str] = None,
        client_name: Optional[str] = None,
        company_name: Optional[str] = None,
    ) -> RawDeck:
        """
        Parse a .pptx file and return a fully populated RawDeck.

        Parameters
        ----------
        file_path     : Path to the .pptx file.
        deck_id       : Unique identifier for this deck (e.g. 'client_q2_2026').
        meeting_date  : ISO-8601 date string of the meeting, e.g. '2026-04-01'.
        quarter       : Quarter label, e.g. 'Q2'.
        half_year     : Half-year label, e.g. 'H1'.
        year          : Calendar year, e.g. 2026.
        period_label  : Free-form period label, e.g. 'Q2 2026 QBR'.
        client_name   : Client name (used for footer noise detection).
        company_name  : Company name (used for footer noise detection).
        """
        file_path = Path(file_path)
        logger.info("Extracting deck: %s  (deck_id=%s)", file_path, deck_id)

        prs = Presentation(str(file_path))
        section_map = _build_section_map(prs)

        # Build reverse map: slide_number â†’ section_name
        slide_to_section: Dict[int, str] = {}
        for section_name, slide_nums in section_map.items():
            for sn in slide_nums:
                slide_to_section[sn] = section_name

        slides: List[RawSlide] = []

        for slide_idx, slide in enumerate(prs.slides):
            slide_number = slide_idx + 1
            slide_id = f"{deck_id}_slide_{slide_number:03d}"
            title = _extract_slide_title(slide)
            notes = _extract_notes(slide)
            section = slide_to_section.get(slide_number)
            layout_name: Optional[str] = None
            try:
                layout_name = slide.slide_layout.name
            except Exception:
                pass

            # Extract all elements (recursive for groups)
            elements = _extract_shapes(
                slide.shapes,
                deck_id=deck_id,
                slide_number=slide_number,
            )
            _assign_reading_order(elements)

            raw_slide = RawSlide(
                deck_id=deck_id,
                slide_number=slide_number,
                slide_id=slide_id,
                title=title,
                section=section,
                elements=elements,
                notes=notes,
                layout_name=layout_name,
            )
            slides.append(raw_slide)
            logger.debug(
                "  Slide %d: title=%r  elements=%d  section=%r",
                slide_number,
                title,
                len(elements),
                section,
            )

        deck = RawDeck(
            deck_id=deck_id,
            file_path=str(file_path),
            meeting_date=meeting_date,
            quarter=quarter,
            half_year=half_year,
            year=year,
            period_label=period_label or self._auto_period_label(quarter, half_year, year),
            client_name=client_name,
            company_name=company_name,
            slides=slides,
            section_map=section_map,
        )

        logger.info(
            "Extraction complete: deck_id=%s  slides=%d  total_elements=%d",
            deck_id,
            deck.total_slides,
            sum(len(s.elements) for s in deck.slides),
        )
        return deck

    @staticmethod
    def _auto_period_label(
        quarter: Optional[str],
        half_year: Optional[str],
        year: Optional[int],
    ) -> Optional[str]:
        parts = [p for p in [quarter or half_year, str(year) if year else None] if p]
        return " ".join(parts) if parts else None

