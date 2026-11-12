"""
extraction/extractor.py

Stage 1 — Raw PPT Extraction.

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
    # OLE objects (type 7) — used by Excel-linked charts embedded in slides.
    # python-pptx exposes them as GraphicFrame shapes; we inspect the frame
    # to determine whether they contain a chart or table, and fall back to
    # IMAGE (a safe inert type) if neither is detectable.
    7:                              ElementType.IMAGE,  # EMBEDDED_OLE_OBJECT
}


def _element_type_from_shape(shape: BaseShape) -> ElementType:
    try:
        mso = shape.shape_type
        mso_int = int(mso)
        et = _MSO_TO_ELEMENT_TYPE.get(mso_int)
        if et is not None:
            return et
        # GraphicFrame shapes (OLE / embedded objects) that are not in the map:
        # check whether python-pptx can see a chart or table inside them.
        if isinstance(shape, GraphicFrame):
            try:
                if shape.has_chart:
                    return ElementType.CHART
            except Exception:
                pass
            try:
                if shape.has_table:
                    return ElementType.TABLE
            except Exception:
                pass
            return ElementType.IMAGE  # treat as inert embedded object
        return ElementType.UNKNOWN
    except Exception:
        return ElementType.UNKNOWN


# ---------------------------------------------------------------------------
# Text sanitisation helper
# ---------------------------------------------------------------------------

def _sanitise_text(text: str) -> str:
    """
    Strip PowerPoint-specific control characters from extracted text.

    PowerPoint uses U+000B (vertical tab / <a:br/>) as an in-paragraph
    line break.  python-pptx surfaces this as a literal \\x0b character in
    every .text property.  Left in place it corrupts section map keys,
    slide titles, and SCU content.  Replace it with a regular space so the
    surrounding words are not concatenated (e.g. "Leadership Introductions"
    not "LeadershipIntroductions").

    Also strips the zero-width no-break space (U+FEFF) that occasionally
    appears at the start of text boxes authored on older PowerPoint versions.
    """
    return text.replace("\x0b", " ").replace("\u00ad", "").replace("\ufeff", "").strip()


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
            line = _sanitise_text("".join(run.text for run in para.runs))
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
                text = _sanitise_text(cell.text_frame.text) if cell.text_frame else ""
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
# Meeting type detection
# ---------------------------------------------------------------------------

# Ordered list of (regex_pattern, canonical_label) pairs.
# First match wins. Checked against the combined text of the first two slides.
_MEETING_TYPE_PATTERNS = [
    (re.compile(r'kick[\-\s]?off\s+meeting', re.I), 'Kick-Off Meeting'),
    (re.compile(r'governance\s+meeting',       re.I), 'Governance Meeting'),
    (re.compile(r'steering\s+committee',       re.I), 'Steering Committee'),
    (re.compile(r'\bqbr\b',                   re.I), 'QBR'),
    (re.compile(r'quarterly\s+business\s+review', re.I), 'QBR'),
    (re.compile(r'business\s+review',          re.I), 'Business Review'),
    (re.compile(r'annual\s+review',            re.I), 'Annual Review'),
]


def _detect_meeting_type(slides: List, deck_id: str = "", file_path: str = "") -> Optional[str]:
    """
    Scan for a known meeting-type keyword in (priority order):
      1. The filename stem — highest signal (e.g. '…_qbr_v1.pptx')
      2. The deck_id string
      3. Combined text of the first two slides

    Returns the canonical label (e.g. 'Kick-Off Meeting', 'QBR') or None.
    """
    # Build search sources in priority order
    search_sources: List[str] = []
    if file_path:
        search_sources.append(Path(file_path).stem.replace("_", " ").replace("-", " "))
    if deck_id:
        search_sources.append(deck_id.replace("_", " ").replace("-", " "))
    title_slides = slides[:2] if slides else []
    combined_slides = " ".join(
        el.text or ""
        for slide in title_slides
        for el in slide.elements
        if el.text
    )
    search_sources.append(combined_slides)

    for text in search_sources:
        text_lower = text.lower()
        for pattern, label in _MEETING_TYPE_PATTERNS:
            if pattern.search(text_lower):
                return label
    return None


# ---------------------------------------------------------------------------
# Quarter / half-year auto-detection
# ---------------------------------------------------------------------------

# Ordered patterns tried against the filename stem first, then the
# combined text of the first two slides.  First match wins.
_QUARTER_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\bq([1-4])\b',           re.I), "Q{0}"),   # Q1 … Q4
    (re.compile(r'\bquarter\s*([1-4])\b',  re.I), "Q{0}"),   # Quarter 1
    (re.compile(r'\b([1-4])(?:st|nd|rd|th)?\s+quarter\b', re.I), "Q{0}"),
]

_HALF_YEAR_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\bh([12])\b',          re.I), "H{0}"),   # H1 / H2
    (re.compile(r'\bhalf\s*([12])\b',    re.I), "H{0}"),   # Half 1
    (re.compile(r'\b(first|1st)\s+half\b', re.I), "H1"),
    (re.compile(r'\b(second|2nd)\s+half\b', re.I), "H2"),
]


def _detect_quarter_and_half_year(
    deck_id: str,
    file_path: Optional[str],
    slides: List,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Auto-detect quarter (e.g. 'Q1') and half_year (e.g. 'H1') from:
      1. The filename stem (highest signal — usually contains 'Q1', 'H2' etc.)
      2. The deck_id string (derived from the filename, so same signal)
      3. Combined text of the first two slides (title/agenda slides)

    Returns (quarter, half_year).  quarter takes priority over half_year
    when both signals are found in the same source.
    """
    # Build candidate strings in priority order
    search_targets: List[str] = []
    if file_path:
        search_targets.append(Path(file_path).stem)
    search_targets.append(deck_id)
    combined_slides = " ".join(
        el.text or ""
        for slide in (slides[:2] if slides else [])
        for el in slide.elements
        if el.text
    )
    search_targets.append(combined_slides)

    quarter: Optional[str]   = None
    half_year: Optional[str] = None

    for text in search_targets:
        if not quarter:
            for pat, fmt in _QUARTER_PATTERNS:
                m = pat.search(text)
                if m:
                    # fmt is either "Q{0}" (use group 1) or a fixed string
                    if "{0}" in fmt:
                        quarter = fmt.format(m.group(1).upper())
                    else:
                        quarter = fmt
                    logger.info(
                        "Auto-detected quarter=%r from %r",
                        quarter, text[:60],
                    )
                    break
        if not half_year:
            for pat, fmt in _HALF_YEAR_PATTERNS:
                m = pat.search(text)
                if m:
                    if "{0}" in fmt:
                        half_year = fmt.format(m.group(1).upper())
                    else:
                        half_year = fmt
                    logger.info(
                        "Auto-detected half_year=%r from %r",
                        half_year, text[:60],
                    )
                    break
        # Once both are found there is nothing more to search
        if quarter and half_year:
            break

    return quarter, half_year


# ---------------------------------------------------------------------------
# Meeting date auto-detection
# ---------------------------------------------------------------------------

# Month names for ordinal / written-out date patterns.
_MONTH_NAMES = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)

# Ordered list of (compiled_regex, strptime_format_or_callable) pairs.
# The first pattern that matches wins.  A callable receives the Match object
# and returns an ISO-8601 string (YYYY-MM-DD) or None.
_DATE_PATTERNS: List[Tuple[re.Pattern, object]] = []


def _register_date_pattern(pattern: str, fmt_or_fn: object) -> None:
    _DATE_PATTERNS.append((re.compile(pattern, re.I), fmt_or_fn))


# ISO / numeric: 2026-03-10, 2026/03/10, 10/03/2026, 10-03-2026
_register_date_pattern(
    r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b",
    lambda m: f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
)
_register_date_pattern(
    r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b",
    lambda m: f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}",
)

# "10th March 2026", "3rd Jan 2026", "21st December 2025"
_register_date_pattern(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH_NAMES + r"\s+(\d{4})\b",
    None,  # handled specially below — month name needs parsing
)

# "March 10, 2026", "March 10 2026"
_register_date_pattern(
    _MONTH_NAMES + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    None,  # handled specially below
)

# "10 March 2026" (no ordinal suffix)
_register_date_pattern(
    r"\b(\d{1,2})\s+" + _MONTH_NAMES + r"\s+(\d{4})\b",
    None,
)


_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_month_name(text: str) -> Optional[int]:
    """Return 1-12 for a month name substring, or None."""
    key = text[:3].lower()
    return _MONTH_MAP.get(key)


def _extract_meeting_date(slides: List) -> Optional[str]:
    """
    Scan the first two slides for a date string and return it as ISO-8601
    (YYYY-MM-DD).  Only fires when no meeting_date was passed in by the
    caller.

    Handles formats commonly seen on ICG QBR title slides:
      - "10th March 2026"
      - "3 Jan 2026"
      - "March 10, 2026"
      - "2026-03-10"
      - "10/03/2026"
    """
    title_slides = slides[:2] if slides else []
    texts = [
        el.text
        for slide in title_slides
        for el in slide.elements
        if el.text
    ]

    for text in texts:
        for pattern, fmt_or_fn in _DATE_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            try:
                if callable(fmt_or_fn):
                    result = fmt_or_fn(m)
                    if result:
                        return result
                else:
                    # Month-name patterns — parse manually
                    matched = m.group(0)
                    # Find a 4-digit year
                    year_m = re.search(r"\b(\d{4})\b", matched)
                    if not year_m:
                        continue
                    year = int(year_m.group(1))
                    # Find a month name
                    month_m = re.search(_MONTH_NAMES, matched, re.I)
                    if not month_m:
                        continue
                    month = _parse_month_name(month_m.group(0))
                    if not month:
                        continue
                    # Find a 1-2 digit day
                    day_m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", matched)
                    if not day_m:
                        continue
                    day = int(day_m.group(1))
                    if not (1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2100):
                        continue
                    return f"{year:04d}-{month:02d}-{day:02d}"
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Image-only chart detection
# ---------------------------------------------------------------------------

# Keywords that suggest an IMAGE shape is a chart rendered as a raster image.
_IMAGE_CHART_KEYWORDS = {
    'gwp', 'chart', 'trend', 'growth', 'year', 'premium', 'revenue',
    'performance', 'split', 'mix', '5-year', 'five year', 'ytd', 'qoq',
    'yoy', 'annual', 'quarterly', 'bar', 'line', 'graph',
}


def _is_image_only_chart(shape: BaseShape, alt_text: Optional[str]) -> bool:
    """
    Return True if *shape* is an IMAGE element that appears to be a chart
    rendered as a raster image (no underlying PPTX chart XML).
    Detection: the shape is a picture/media type (no .has_chart), and its
    alt-text or name attribute contains chart-like keywords.
    """
    try:
        if not hasattr(shape, "shape_type"):
            return False
        mso = int(shape.shape_type)
        if mso not in (int(MSO_SHAPE_TYPE.PICTURE), int(MSO_SHAPE_TYPE.MEDIA)):
            return False
        if getattr(shape, "has_chart", False):
            return False
        haystack = (alt_text or "").lower()
        try:
            cNvPr = shape._element.find(".//" + qn("p:cNvPr"))
            if cNvPr is not None:
                haystack += " " + (cNvPr.get("name") or "").lower()
                haystack += " " + (cNvPr.get("descr") or "").lower()
        except Exception:
            pass
        return any(kw in haystack for kw in _IMAGE_CHART_KEYWORDS)
    except Exception:
        return False


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

        img_only_chart = (
            _is_image_only_chart(shape, alt_text)
            if etype == ElementType.IMAGE else False
        )

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
            is_image_only_chart=img_only_chart,
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

    Tier 0 — Native XML section map (works for natively authored PPTX files).
    Tier 1 — Layout-name fallback: when the XML walk returns nothing (e.g. a
              PDF-converted PPTX that has lost its section XML), infer section
              boundaries from slide layout names that contain the keyword
              "divider" (case-insensitive).  The section name is taken from the
              slide's title placeholder text; if that is also absent a generated
              label "Section_<slide_number>" is used.  All slides from one
              divider up to (but not including) the next divider are grouped
              into that section.  Slides that precede the first divider are
              collected under the label "Introduction".
    """
    section_map: Dict[str, List[int]] = {}

    # ── Tier 0: native XML ───────────────────────────────────────────────────
    try:
        sldIdLst = prs.slides._sldIdLst
        # Build slide-id → 1-based index map
        id_to_idx = {
            el.get("id"): i + 1
            for i, el in enumerate(sldIdLst)
        }

        # Walk sectionLst in presentation XML
        prs_el = prs.core_properties._element  # not ideal — use prs._element
        prs_el = prs.slides._sldIdLst.getparent().getparent()
        ext_lst = prs_el.find(qn("p:extLst"))
        if ext_lst is not None:
            for ext in ext_lst:
                for sec_lst in ext:
                    tag = sec_lst.tag.split("}")[-1] if "}" in sec_lst.tag else sec_lst.tag
                    if tag == "sectionLst":
                        for section in sec_lst:
                            name = section.get("name", "Unnamed Section")
                            name = _sanitise_text(name) or "Unnamed Section"
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
        logger.debug("Section map XML extraction failed: %s", exc)

    if section_map:
        return section_map

    # ── Tier 1: layout-name divider fallback ─────────────────────────────────
    logger.debug(
        "Section map XML walk returned nothing — trying layout-name fallback"
    )
    try:
        total = len(prs.slides)
        # Identify divider slide indices (0-based) and their section names
        dividers: List[Tuple[int, str]] = []  # (slide_index, section_name)
        for idx, slide in enumerate(prs.slides):
            layout_name = ""
            try:
                layout_name = slide.slide_layout.name or ""
            except Exception:
                pass
            if "divider" not in layout_name.lower():
                continue
            # Derive section name from the slide's title placeholder
            name: Optional[str] = None
            try:
                t = slide.shapes.title
                if t:
                    name = _sanitise_text(t.text) or None
            except Exception:
                pass
            if not name:
                # Fallback: largest-font non-placeholder text box on this slide
                try:
                    candidates = []
                    for shape in slide.shapes:
                        if not shape.has_text_frame:
                            continue
                        txt = _sanitise_text(shape.text_frame.text)
                        if not txt or getattr(shape, "is_placeholder", False):
                            continue
                        fs = 0.0
                        try:
                            raw_fs = shape.text_frame.paragraphs[0].runs[0].font.size
                            if raw_fs:
                                fs = raw_fs.pt
                        except Exception:
                            pass
                        candidates.append((-fs, txt))
                    if candidates:
                        candidates.sort()
                        name = candidates[0][1][:80]
                except Exception:
                    pass
            if not name:
                name = f"Section_{idx + 1}"
            dividers.append((idx, name))

        if not dividers:
            logger.debug("Layout-name fallback: no divider slides found")
            return section_map

        # Build section ranges.
        # Slides before the first divider → "Introduction".
        # Each divider slide starts a section that runs up to the next divider.
        boundaries: List[Tuple[int, int, str]] = []  # (start_idx, end_excl, name)
        if dividers[0][0] > 0:
            boundaries.append((0, dividers[0][0], "Introduction"))
        for i, (start_idx, sec_name) in enumerate(dividers):
            end_idx = dividers[i + 1][0] if i + 1 < len(dividers) else total
            boundaries.append((start_idx, end_idx, sec_name))

        for start_idx, end_idx, sec_name in boundaries:
            slide_numbers = list(range(start_idx + 1, end_idx + 1))  # 1-based
            if slide_numbers:
                section_map[sec_name] = slide_numbers

        logger.debug(
            "Layout-name fallback produced %d sections: %s",
            len(section_map),
            list(section_map.keys()),
        )
    except Exception as exc:
        logger.debug("Section map layout fallback failed: %s", exc)

    if section_map:
        return section_map

    # ── Tier 2: shape-count / section-divider heuristic ──────────────────────
    # When neither native XML sections nor layout "divider" names are present
    # (common in manually authored decks that use a custom section-intro slide
    # layout with no special name), identify section-divider slides by their
    # visual signature:
    #
    #   - Few shapes overall (≤ 6) — a divider slide has almost no content
    #   - No table or chart shapes — data slides always have at least one
    #   - Contains at least one non-trivial text string (≥ 4 chars, not purely
    #     numeric) that can serve as the section name
    #   - The matching text is NOT just the slide number or a one-word label
    #
    # Slides that satisfy all conditions and sit at least 2 slides apart from
    # each other are treated as section boundaries.  Slides that precede the
    # first boundary are collected under "Introduction".
    #
    # This heuristic deliberately errs on the side of NOT firing: if fewer
    # than 2 divider candidates are found, no section map is produced rather
    # than creating a single-section map with little value.
    logger.debug(
        "Tier 1 fallback found nothing — trying shape-count heuristic (Tier 2)"
    )
    try:
        total = len(prs.slides)
        dividers_t2: List[Tuple[int, str]] = []  # (slide_index, section_name)

        for idx, slide in enumerate(prs.slides):
            shapes = list(slide.shapes)

            # Skip known cover / back-cover layouts — these are never section
            # dividers, and their content (legal text, logos) would produce
            # nonsensical section names.
            layout_name_t2 = ""
            try:
                layout_name_t2 = (slide.slide_layout.name or "").lower()
            except Exception:
                pass
            if any(kw in layout_name_t2 for kw in ("back cover", "cover", "end slide")):
                continue

            # Must have few shapes
            if len(shapes) > 6:
                continue

            # Must not contain a table or chart (those are content slides)
            has_data = False
            for shp in shapes:
                try:
                    if shp.has_table or shp.has_chart:
                        has_data = True
                        break
                except Exception:
                    pass
            if has_data:
                continue

            # Collect all non-trivial text on this slide (ignore slide numbers
            # and short decorative labels like "01", "02", "03").
            # A section name is never longer than 120 characters — anything
            # longer is body copy or a legal disclaimer that leaked in, not a
            # heading.  We filter those out here rather than truncating so that
            # a slide whose only text is a legal block is excluded entirely.
            candidate_texts: List[Tuple[float, str]] = []  # (font_size, text)
            for shp in shapes:
                if not shp.has_text_frame:
                    continue
                # Use only the first paragraph's text as the section label so
                # multi-paragraph shapes (e.g. "Trading Results Q1 2026\nTTM
                # March 2026 vs TTM March 2025") produce a clean heading rather
                # than a multi-line string.
                try:
                    first_para = _sanitise_text(
                        "".join(run.text for run in shp.text_frame.paragraphs[0].runs)
                    ) if shp.text_frame.paragraphs else ""
                    txt = first_para or _sanitise_text(shp.text_frame.text).split("\n")[0]
                except Exception:
                    txt = _sanitise_text(shp.text_frame.text).split("\n")[0]
                # Skip: empty, purely numeric (slide numbers), very short,
                # or suspiciously long (legal / body copy — not a heading).
                if not txt or txt.isdigit() or len(txt) < 4 or len(txt) > 120:
                    continue
                # Prefer larger-font text as the section label
                fs = 0.0
                try:
                    raw_fs = shp.text_frame.paragraphs[0].runs[0].font.size
                    if raw_fs:
                        fs = raw_fs.pt
                except Exception:
                    pass
                candidate_texts.append((-fs, txt))

            if not candidate_texts:
                continue

            # Pick the largest-font (most prominent) text as the section name
            candidate_texts.sort()
            section_name = candidate_texts[0][1][:80]

            # Avoid treating the agenda/cover/attendees slide as a divider:
            # those slides have multiple distinct text items.  A real divider
            # slide usually has only 1–2 meaningful text items.
            if len(candidate_texts) > 3:
                continue

            dividers_t2.append((idx, section_name))

        # Require at least 2 divider candidates — a single candidate is likely
        # a false positive (e.g. a blank placeholder slide).
        if len(dividers_t2) < 2:
            logger.debug(
                "Tier 2 heuristic: fewer than 2 divider candidates found (%d) — skipping",
                len(dividers_t2),
            )
            return section_map

        # Build section ranges (same logic as Tier 1).
        boundaries_t2: List[Tuple[int, int, str]] = []
        if dividers_t2[0][0] > 0:
            boundaries_t2.append((0, dividers_t2[0][0], "Introduction"))
        for i, (start_idx, sec_name) in enumerate(dividers_t2):
            end_idx = dividers_t2[i + 1][0] if i + 1 < len(dividers_t2) else total
            boundaries_t2.append((start_idx, end_idx, sec_name))

        for start_idx, end_idx, sec_name in boundaries_t2:
            slide_numbers = list(range(start_idx + 1, end_idx + 1))  # 1-based
            if slide_numbers:
                section_map[sec_name] = slide_numbers

        logger.debug(
            "Tier 2 heuristic produced %d sections: %s",
            len(section_map),
            list(section_map.keys()),
        )
    except Exception as exc:
        logger.debug("Section map Tier 2 heuristic failed: %s", exc)

    if section_map:
        return section_map

    # ── Tier 3: per-slide title fallback ─────────────────────────────────────
    # Some decks (e.g. a regional QBR with one country per slide) have no
    # divider slides at all — every content slide IS its own section, and
    # that section's name is simply the slide's own title ("Canada",
    # "Australia", "UK", ...). Tiers 0-2 all assume a divider/boundary slide
    # introduces a *range* of following content slides, so they correctly
    # find nothing here. This tier handles that different-but-common shape:
    # treat each content slide as a single-slide section named after its own
    # already-extracted title.
    #
    # This never invents a section label — it reuses the exact title text
    # already produced by _extract_slide_title() — and never clusters slides
    # into a larger region/group that isn't explicitly labelled in the deck
    # (e.g. it will NOT guess that "Canada" and "Australia" belong to the
    # same region just because they are adjacent). That broader grouping, if
    # wanted, would require genuine evidence (e.g. an explicit "APAC"/"EMEA"
    # label) and is deliberately left for a later stage/human judgement.
    #
    # Guardrails against false positives on non-geographic decks:
    #   - Cover/back-cover/title-slide layouts are always excluded.
    #   - A candidate title must be short and label-like (<=8 words,
    #     <=80 chars) — a long sentence is body copy, not a section name.
    #   - At least 2 candidate slides with at least 2 distinct titles are
    #     required; a deck where every slide repeats the same title is not
    #     a per-slide section structure and produces no section map here.
    logger.debug(
        "Tier 2 heuristic found nothing — trying per-slide title fallback (Tier 3)"
    )
    try:
        candidates_t3: List[Tuple[int, str]] = []  # (slide_index, title)
        for idx, slide in enumerate(prs.slides):
            layout_name_t3 = ""
            try:
                layout_name_t3 = (slide.slide_layout.name or "").lower()
            except Exception:
                pass
            if any(
                kw in layout_name_t3
                for kw in ("back cover", "cover", "end slide", "title slide")
            ):
                continue

            title = _extract_slide_title(slide)
            if not title:
                continue
            title = title.strip()
            if not title or len(title) > 80 or len(title.split()) > 8:
                continue
            candidates_t3.append((idx, title))

        distinct_titles_t3 = {t for _, t in candidates_t3}
        if len(candidates_t3) < 2 or len(distinct_titles_t3) < 2:
            logger.debug(
                "Tier 3 heuristic: insufficient distinct per-slide titles "
                "(%d candidate slides, %d distinct titles) — skipping",
                len(candidates_t3), len(distinct_titles_t3),
            )
            return section_map

        for idx, title in candidates_t3:
            section_map.setdefault(title, []).append(idx + 1)  # 1-based

        logger.debug(
            "Tier 3 heuristic produced %d per-slide section(s): %s",
            len(section_map),
            list(section_map.keys()),
        )
    except Exception as exc:
        logger.debug("Section map Tier 3 heuristic failed: %s", exc)

    return section_map

# ---------------------------------------------------------------------------
# Slide title helper
# ---------------------------------------------------------------------------

def _extract_slide_title(slide) -> Optional[str]:
    # Attempt 1: python-pptx shortcut
    try:
        return _sanitise_text(slide.shapes.title.text) or None
    except Exception:
        pass
    # Attempt 2: any TITLE or CENTER_TITLE placeholder
    try:
        for shape in slide.shapes:
            if shape.is_placeholder:
                ph = shape.placeholder_format
                if ph.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE):
                    txt = _sanitise_text(shape.text_frame.text)
                    if txt:
                        return txt
    except Exception:
        pass
    # Attempt 3: topmost substantial non-placeholder text box.
    # Skipped for Back Cover and purely decorative layouts where extracting
    # arbitrary text as a "title" would be misleading.
    try:
        layout_name = ""
        try:
            layout_name = (slide.slide_layout.name or "").lower()
        except Exception:
            pass
        if "back cover" not in layout_name and "cover" not in layout_name:
            candidates = []
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                if getattr(shape, "is_placeholder", False):
                    continue
                txt = _sanitise_text(shape.text_frame.text)
                # Must be at least 3 characters and no more than 120 to be title-like
                if not txt or len(txt) < 3 or len(txt) > 120:
                    continue
                y = shape.top if shape.top is not None else int(1e12)
                fs = 0.0
                try:
                    raw_fs = shape.text_frame.paragraphs[0].runs[0].font.size
                    if raw_fs:
                        fs = raw_fs.pt
                except Exception:
                    pass
                candidates.append((y, -fs, txt))
            if candidates:
                candidates.sort()
                return candidates[0][2]
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

        detected_meeting_type = _detect_meeting_type(
            slides, deck_id=deck_id, file_path=str(file_path),
        )
        if detected_meeting_type:
            logger.info(
                "Detected meeting type for deck_id=%s: %s",
                deck_id, detected_meeting_type,
            )

        # ── Auto-detect quarter / half_year from filename + slide text ────────
        if not quarter and not half_year:
            quarter, half_year = _detect_quarter_and_half_year(
                deck_id=deck_id,
                file_path=str(file_path),
                slides=slides,
            )
        elif not quarter:
            # half_year supplied but quarter still missing — try filename only
            _q, _h = _detect_quarter_and_half_year(
                deck_id=deck_id, file_path=str(file_path), slides=slides,
            )
            quarter = _q  # may still be None, that's fine

        # ── Auto-detect meeting_date from slide text if not supplied ──────────
        if not meeting_date:
            meeting_date = _extract_meeting_date(slides)
            if meeting_date:
                logger.info(
                    "Auto-detected meeting_date for deck_id=%s: %s",
                    deck_id, meeting_date,
                )

        # ── Auto-resolve company_name via carrier alias index if not supplied ─
        # Scan the first two slides for any known carrier name or alias and
        # resolve it to the canonical carrier label from config.yaml.
        if not company_name:
            from recap.config import settings as _settings
            alias_index = _settings.carrier_alias_index
            title_texts = [
                el.text
                for slide in slides[:2]
                for el in slide.elements
                if el.text
            ]
            combined_title = " ".join(title_texts)
            # Try each alias (longest first so "QBE Europe" beats "QBE")
            sorted_aliases = sorted(alias_index.keys(), key=len, reverse=True)
            for alias in sorted_aliases:
                if re.search(r"\b" + re.escape(alias) + r"\b", combined_title, re.I):
                    company_name = alias_index[alias]
                    logger.info(
                        "Auto-resolved company_name for deck_id=%s: %r → %r",
                        deck_id, alias, company_name,
                    )
                    break

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
            meeting_type=detected_meeting_type,
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

