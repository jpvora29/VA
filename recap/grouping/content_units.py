"""
grouping/content_units.py

Stage 3 — Semantic Content Unit (SCU) construction.

Groups filtered PPT elements into semantically coherent business points.
Grouping uses a layered strategy (in priority order):

  1. python-pptx group shapes    → all children become one SCU
  2. Charts                      → chart + nearby labels/title as one SCU
  3. Tables                      → whole table as one SCU
  4. Spatial proximity clusters  → nearby text elements merged into SCUs
  5. Individual elements         → anything remaining becomes its own SCU

Every SCU retains the IDs of all contributing elements for provenance.

KPI label/value pairing
------------------------
Strategy 4's proximity clustering merges elements purely by raw centroid
distance (< PROXIMITY_EMU). This works for most layouts, but KPI-card
grids intentionally put a large numeric value ("65%", "e11m+") and its
small caption ("GWP Growth in Germany") far enough apart, vertically,
that their centroids fall outside PROXIMITY_EMU even though the two
boxes are clearly one visual unit - the value box is tall (to fit a big
font) so its centre sits well above the caption directly beneath it.
Splitting them produces a bare "65%" SCU with no name and an orphaned
caption SCU with no value, both useless on their own.

To fix this without loosening PROXIMITY_EMU globally (which would over-merge
unrelated nearby text), a second, narrowly-scoped check -
_is_kpi_label_value_pair() - also merges two elements when one is a bare
numeric/percentage/currency value and the other is a short non-numeric
caption, provided the two boxes are close edge-to-edge and substantially
aligned on one axis (stacked or side-by-side). This never fires for two
captions, two values, or two unrelated short text fragments.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, List, Optional, Set, Tuple

from recap.schemas.raw_extraction import ElementType, RawElement, RawSlide
from recap.schemas.content_units import (
    ContentUnitType,
    GroupingMethod,
    SemanticContentUnit,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Spatial proximity threshold — elements within this distance (EMU) may be
# grouped. ~0.5 inch = 457,200 EMU; ~0.75 inch = 685,800 EMU.
PROXIMITY_EMU = 685_800

# KPI label/value pairing thresholds — see module docstring. These are
# deliberately tighter than PROXIMITY_EMU on the gap side (edge-to-edge,
# not centroid) but require strong axis alignment, so they only catch
# genuine stacked/adjacent value+caption pairs, not arbitrary nearby text.
KPI_PAIR_MAX_EDGE_GAP_EMU = 200_000       # ~0.22 inch edge-to-edge gap
KPI_PAIR_MIN_AXIS_OVERLAP = 0.6           # 60% overlap on x or y axis
KPI_VALUE_MAX_WORDS = 6                   # "e11m+", "65%", "$0.5BN of growth"
KPI_CAPTION_MAX_WORDS = 8                 # "GWP Growth vs Prior Year"

# Minimum characters for a content unit to be considered substantive
MIN_CONTENT_LENGTH = 2

# Regex to detect numeric / KPI-like values
_RE_NUMERIC = re.compile(r"\d")
_RE_PERCENTAGE = re.compile(r"\d[\d,.]*\s*%")
_RE_CURRENCY = re.compile(r"[$£€¥]\s*[\d,.]+|[\d,.]+\s*[MBKTmbtk](?:\b|$)")
_RE_TREND = re.compile(r"[▲▼↑↓➚➘+\-]|\bYoY\b|\bQoQ\b|\bHoH\b|\bvs\.?\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# ID generator
# ---------------------------------------------------------------------------

def _make_scu_id(deck_id: str, slide_number: int, index: int) -> str:
    return f"CU_{deck_id}_s{slide_number:03d}_{index:03d}"


# ---------------------------------------------------------------------------
# Bounding box helpers
# ---------------------------------------------------------------------------

def _bounding_box(
    elements: List[RawElement],
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    xs = [e.x for e in elements if e.x is not None]
    ys = [e.y for e in elements if e.y is not None]
    x2s = [e.x + e.width for e in elements if e.x is not None and e.width is not None]
    y2s = [e.y + e.height for e in elements if e.y is not None and e.height is not None]
    if not xs:
        return None, None, None, None
    x = min(xs)
    y = min(ys)
    return x, y, max(x2s) - x if x2s else None, max(y2s) - y if y2s else None


def _centre(el: RawElement) -> Optional[Tuple[float, float]]:
    if el.x is None or el.y is None or el.width is None or el.height is None:
        return None
    return el.x + el.width / 2, el.y + el.height / 2


def _distance(a: RawElement, b: RawElement) -> float:
    ca, cb = _centre(a), _centre(b)
    if ca is None or cb is None:
        return float("inf")
    return ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5


def _is_bare_kpi_value_text(text: str) -> bool:
    """
    True if *text* is essentially just a numeric/percentage/currency value
    with little or no other wording (e.g. "65%", "e11m+", "$0.5BN of
    growth\nover 5 years") — a value box that needs a caption to be
    meaningful on its own.
    """
    text = text.strip()
    if not text:
        return False
    has_value = bool(_RE_PERCENTAGE.search(text) or _RE_CURRENCY.search(text))
    if not has_value:
        return False
    return len(text.split()) <= KPI_VALUE_MAX_WORDS


def _is_caption_like_text(text: str) -> bool:
    """
    True if *text* reads like a short caption/label with no value of its
    own (e.g. "GWP Growth in Germany") — the kind of fragment that names
    a nearby bare value.
    """
    text = text.strip()
    if not text:
        return False
    if _RE_PERCENTAGE.search(text) or _RE_CURRENCY.search(text):
        return False
    return len(text.split()) <= KPI_CAPTION_MAX_WORDS


def _edge_gap(a: RawElement, b: RawElement) -> float:
    """Shortest edge-to-edge distance between two bounding boxes (0 if they overlap)."""
    if a.x is None or a.y is None or a.width is None or a.height is None:
        return float("inf")
    if b.x is None or b.y is None or b.width is None or b.height is None:
        return float("inf")
    ax1, ay1, ax2, ay2 = a.x, a.y, a.x + a.width, a.y + a.height
    bx1, by1, bx2, by2 = b.x, b.y, b.x + b.width, b.y + b.height
    dx = max(ax1 - bx2, bx1 - ax2, 0)
    dy = max(ay1 - by2, by1 - ay2, 0)
    return (dx ** 2 + dy ** 2) ** 0.5


def _axis_overlap_fraction(a: RawElement, b: RawElement, axis: str) -> float:
    """Fraction of the smaller box's extent on *axis* ("x" or "y") that overlaps the other box."""
    if axis == "x":
        a1, a2 = a.x, a.x + a.width
        b1, b2 = b.x, b.x + b.width
    else:
        a1, a2 = a.y, a.y + a.height
        b1, b2 = b.y, b.y + b.height
    inter = max(0, min(a2, b2) - max(a1, b1))
    min_extent = min(a2 - a1, b2 - b1)
    return inter / min_extent if min_extent else 0.0


def _is_kpi_label_value_pair(a: RawElement, b: RawElement) -> bool:
    """
    True if *a* and *b* look like a KPI value box and its caption that
    proximity clustering alone (centroid distance < PROXIMITY_EMU) would
    otherwise split apart — see module docstring "KPI label/value pairing".

    Requires:
      - exactly one of the two is a bare numeric/%/currency value and the
        other is a short, non-numeric caption (never two values or two
        captions);
      - the boxes are close edge-to-edge (< KPI_PAIR_MAX_EDGE_GAP_EMU);
      - the boxes are substantially aligned on at least one axis
        (>= KPI_PAIR_MIN_AXIS_OVERLAP overlap on x or y), i.e. they are
        stacked or sit side-by-side rather than diagonally offset.
    """
    a_text, b_text = a.effective_text(), b.effective_text()
    a_is_value, b_is_value = _is_bare_kpi_value_text(a_text), _is_bare_kpi_value_text(b_text)
    a_is_caption, b_is_caption = _is_caption_like_text(a_text), _is_caption_like_text(b_text)

    is_pair = (a_is_value and b_is_caption and not b_is_value) or (
        b_is_value and a_is_caption and not a_is_value
    )
    if not is_pair:
        return False

    if a.x is None or b.x is None:
        return False
    if _edge_gap(a, b) >= KPI_PAIR_MAX_EDGE_GAP_EMU:
        return False

    overlap = max(_axis_overlap_fraction(a, b, "x"), _axis_overlap_fraction(a, b, "y"))
    return overlap >= KPI_PAIR_MIN_AXIS_OVERLAP


# ---------------------------------------------------------------------------
# Content analysis helpers
# ---------------------------------------------------------------------------

def _analyse_content(text: str) -> Tuple[bool, bool, bool, bool]:
    """Return (has_numeric, has_percentage, has_currency, has_trend)."""
    return (
        bool(_RE_NUMERIC.search(text)),
        bool(_RE_PERCENTAGE.search(text)),
        bool(_RE_CURRENCY.search(text)),
        bool(_RE_TREND.search(text)),
    )


def _classify_unit_type(elements: List[RawElement]) -> ContentUnitType:
    types = {e.element_type for e in elements}
    if ElementType.CHART in types:
        return ContentUnitType.CHART_INSIGHT
    if ElementType.TABLE in types:
        return ContentUnitType.TABLE_BLOCK
    texts = [e.effective_text() for e in elements]
    combined = " ".join(texts)
    has_num, has_pct, has_cur, _ = _analyse_content(combined)
    if len(elements) >= 2 and (has_num or has_pct or has_cur):
        return ContentUnitType.KPI_CARD
    if len(elements) == 1:
        t = texts[0]
        if "\n" in t or len(t) > 120:
            return ContentUnitType.PARAGRAPH
        if t.startswith(("•", "-", "▪", "*", "–")):
            return ContentUnitType.BULLET_POINT
    return ContentUnitType.MIXED


def _render_chart_content(elements: List[RawElement], context_texts: List[str]) -> str:
    """
    Build a rich, structured text block for a chart SCU.

    Structure:
      [CHART DATA]
      <RawChart.to_text() — title, axis labels, series with cat:val pairs>

      [CHART CONTEXT]
      Nearby labels/titles from surrounding text shapes.
    """
    parts: List[str] = []

    # Chart data block
    for el in elements:
        if el.element_type == ElementType.CHART and el.chart:
            chart_text = el.chart.to_text()
            if chart_text:
                parts.append("[CHART DATA]")
                parts.append(chart_text)
            break

    # Context block — nearby text shapes (title, callouts, legends, footnotes)
    ctx = [t for t in context_texts if t.strip()]
    if ctx:
        parts.append("[CHART CONTEXT]")
        parts.extend(ctx)

    return "\n".join(parts).strip()


def _render_table_row_labelled(table) -> str:
    """
    Render a RawTable as labelled "ColHeader: Value" pipe rows so each
    cell value is explicitly bound to its column header.

    Example output row:
      LoB: Property | GWP: 4,200,000 | GWP YoY: +339.6% | Marsh Book % Change: +5.1%

    This makes it structurally impossible for a downstream LLM to
    attribute a figure (e.g. +339.6%) to the wrong column (e.g. Marsh
    Book % Change) because every value carries its own column label.
    """
    if not table or not table.cells:
        return table.to_text() if table else ""

    grid: List[List[str]] = [
        [""] * table.cols for _ in range(table.rows)
    ]
    for cell in table.cells:
        if 0 <= cell.row < table.rows and 0 <= cell.col < table.cols:
            grid[cell.row][cell.col] = cell.text.strip()

    headers = grid[0] if table.rows > 0 else []
    has_headers = any(h for h in headers)

    lines: List[str] = [f"Table ({table.rows} rows x {table.cols} cols)"]
    if has_headers:
        lines.append("  Headers: " + " | ".join(h or "(blank)" for h in headers))

    data_start = 1 if has_headers else 0
    for ri in range(data_start, table.rows):
        row_cells = grid[ri]
        if not any(c for c in row_cells):
            continue
        if has_headers:
            pairs = []
            for ci, val in enumerate(row_cells):
                header = headers[ci] if ci < len(headers) else ""
                if header and val:
                    pairs.append(f"{header}: {val}")
                elif val:
                    pairs.append(val)
            if pairs:
                lines.append("  " + " | ".join(pairs))
        else:
            lines.append("  " + " | ".join(c for c in row_cells if c))

    return "\n".join(lines)


def _render_table_content(elements: List[RawElement], context_texts: List[str]) -> str:
    """
    Build a rich, structured text block for a table SCU.

    Each data row is rendered as labelled "ColHeader: Value" pipe pairs
    so downstream LLMs cannot misattribute a figure to the wrong column.

    Structure:
      [TABLE DATA]
      <labelled key-value rows>

      [TABLE CONTEXT]
      Nearby caption/title text.
    """
    parts: List[str] = []

    for el in elements:
        if el.element_type == ElementType.TABLE and el.table:
            table_text = _render_table_row_labelled(el.table)
            if table_text:
                parts.append("[TABLE DATA]")
                parts.append(table_text)
            break

    ctx = [t for t in context_texts if t.strip()]
    if ctx:
        parts.append("[TABLE CONTEXT]")
        parts.extend(ctx)

    return "\n".join(parts).strip()


def _build_scu(
    deck_id: str,
    slide: RawSlide,
    elements: List[RawElement],
    index: int,
    grouping_method: GroupingMethod,
) -> Optional[SemanticContentUnit]:
    """Construct a single SCU from a list of elements.

    For chart and table SCUs, dedicated renderers produce structured,
    axis-labelled text blocks instead of the generic effective_text() dump.
    Plain text elements adjacent to the chart/table are captured as context.
    """
    has_chart = any(e.element_type == ElementType.CHART for e in elements)
    has_table = any(e.element_type == ElementType.TABLE for e in elements)

    if has_chart or has_table:
        # Separate structural (chart/table) elements from context (text) elements
        structural = [e for e in elements
                      if e.element_type in (ElementType.CHART, ElementType.TABLE)]
        context_els = [e for e in elements
                       if e.element_type not in (ElementType.CHART, ElementType.TABLE)]
        context_texts = [e.effective_text() for e in context_els
                         if e.effective_text().strip()]

        if has_chart:
            content = _render_chart_content(structural + context_els, context_texts)
        else:
            content = _render_table_content(structural, context_texts)
    else:
        # Plain text / mixed SCU — original behaviour
        texts = [e.effective_text() for e in elements if e.effective_text().strip()]
        content = "\n".join(texts).strip()

    # Prepend warning tag when any element is an image-only chart so
    # downstream prompts know specific values cannot be verified from source.
    if any(getattr(e, "is_image_only_chart", False) for e in elements):
        content = (
            "[IMAGE-ONLY CHART: data not extractable — "
            "do not assert specific values or trend directions]\n"
        ) + content

    if len(content) < MIN_CONTENT_LENGTH:
        return None

    bx, by, bw, bh = _bounding_box(elements)
    has_num, has_pct, has_cur, has_trend = _analyse_content(content)

    reading_orders = [e.reading_order for e in elements if e.reading_order is not None]
    ro = min(reading_orders) if reading_orders else None

    return SemanticContentUnit(
        content_unit_id=_make_scu_id(deck_id, slide.slide_number, index),
        deck_id=deck_id,
        slide_number=slide.slide_number,
        section=slide.section,
        slide_title=slide.title,
        content=content,
        content_unit_type=_classify_unit_type(elements),
        source_element_ids=[e.element_id for e in elements],
        grouping_method=grouping_method,
        bounding_x=bx,
        bounding_y=by,
        bounding_width=bw,
        bounding_height=bh,
        reading_order=ro,
        has_numeric_value=has_num,
        has_percentage=has_pct,
        has_currency=has_cur,
        has_trend_indicator=has_trend,
    )


# ---------------------------------------------------------------------------
# Main builder class
# ---------------------------------------------------------------------------

class ContentUnitBuilder:
    """
    Converts a list of filtered RawElements (for one slide) into a list
    of SemanticContentUnits.

    Usage
    -----
    builder = ContentUnitBuilder()
    scus = builder.build(slide, kept_elements)
    """

    def build(
        self,
        slide: RawSlide,
        kept_elements: List[RawElement],
    ) -> List[SemanticContentUnit]:
        """
        Build SCUs for one slide from its kept (non-noise) elements.
        Returns SCUs sorted by reading order.
        """
        if not kept_elements:
            return []

        deck_id = slide.deck_id
        assigned: Set[str] = set()   # element_ids already placed into an SCU
        scus: List[SemanticContentUnit] = []
        counter = 0

        # --- Index by element_id for fast lookup ---
        elem_map: Dict[str, RawElement] = {e.element_id: e for e in kept_elements}

        # ----------------------------------------------------------------
        # Strategy 1: python-pptx group shapes
        # ----------------------------------------------------------------
        group_elements = [
            e for e in kept_elements
            if e.element_type == ElementType.GROUP
        ]
        for group_el in group_elements:
            if group_el.element_id in assigned:
                continue
            # Gather the group shape itself + all its descendants
            members = [group_el]
            for child_id in group_el.child_element_ids:
                if child_id in elem_map and child_id not in assigned:
                    members.append(elem_map[child_id])
            scu = _build_scu(deck_id, slide, members, counter, GroupingMethod.PPTX_GROUP)
            if scu:
                scus.append(scu)
                counter += 1
                for m in members:
                    assigned.add(m.element_id)

        # ----------------------------------------------------------------
        # Strategy 2: Charts (chart shape + nearby title / label text)
        # ----------------------------------------------------------------
        chart_elements = [
            e for e in kept_elements
            if e.element_type == ElementType.CHART
            and e.element_id not in assigned
        ]
        for chart_el in chart_elements:
            members = [chart_el]
            for other in kept_elements:
                if other.element_id in assigned or other.element_id == chart_el.element_id:
                    continue
                if other.element_type in (ElementType.TEXT_BOX, ElementType.SHAPE, ElementType.PLACEHOLDER):
                    if _distance(chart_el, other) < PROXIMITY_EMU:
                        members.append(other)
            scu = _build_scu(deck_id, slide, members, counter, GroupingMethod.CHART_ELEMENTS)
            if scu:
                scus.append(scu)
                counter += 1
                for m in members:
                    assigned.add(m.element_id)

        # ----------------------------------------------------------------
        # Strategy 3: Tables
        # ----------------------------------------------------------------
        for el in kept_elements:
            if el.element_id in assigned:
                continue
            if el.element_type == ElementType.TABLE:
                scu = _build_scu(deck_id, slide, [el], counter, GroupingMethod.TABLE_ELEMENTS)
                if scu:
                    scus.append(scu)
                    counter += 1
                    assigned.add(el.element_id)

        # ----------------------------------------------------------------
        # Strategy 4: Spatial proximity clustering
        # ----------------------------------------------------------------
        remaining = [e for e in kept_elements if e.element_id not in assigned]
        clusters = self._proximity_cluster(remaining)
        for cluster in clusters:
            if not cluster:
                continue
            scu = _build_scu(deck_id, slide, cluster, counter, GroupingMethod.SPATIAL_PROXIMITY)
            if scu:
                scus.append(scu)
                counter += 1
            for el in cluster:
                assigned.add(el.element_id)

        # ----------------------------------------------------------------
        # Strategy 5: Any remaining unassigned elements as solo SCUs
        # ----------------------------------------------------------------
        for el in kept_elements:
            if el.element_id not in assigned:
                scu = _build_scu(deck_id, slide, [el], counter, GroupingMethod.READING_ORDER)
                if scu:
                    scus.append(scu)
                    counter += 1
                assigned.add(el.element_id)

        # Sort by reading order
        scus.sort(key=lambda s: (s.reading_order if s.reading_order is not None else 9999))
        logger.debug(
            "Slide %d: built %d SCUs from %d kept elements",
            slide.slide_number,
            len(scus),
            len(kept_elements),
        )
        return scus

    # ----------------------------------------------------------------
    # Proximity clustering (single-linkage, greedy)
    # ----------------------------------------------------------------

    def _proximity_cluster(
        self, elements: List[RawElement]
    ) -> List[List[RawElement]]:
        """
        Greedy single-linkage clustering: merge elements within PROXIMITY_EMU.
        Each element starts as its own cluster; adjacent clusters are merged.
        """
        if not elements:
            return []

        # Sort by reading order for deterministic output
        sorted_els = sorted(
            elements,
            key=lambda e: (
                e.y if e.y is not None else int(1e12),
                e.x if e.x is not None else int(1e12),
            ),
        )

        clusters: List[List[RawElement]] = [[sorted_els[0]]]

        for el in sorted_els[1:]:
            merged = False
            for cluster in clusters:
                # Check proximity against any member of the cluster — either
                # plain centroid proximity, or the narrower KPI label/value
                # pairing check for cases proximity alone would miss (see
                # module docstring "KPI label/value pairing").
                for member in cluster:
                    if _distance(el, member) < PROXIMITY_EMU or _is_kpi_label_value_pair(el, member):
                        cluster.append(el)
                        merged = True
                        break
                if merged:
                    break
            if not merged:
                clusters.append([el])

        return clusters
