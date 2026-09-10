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


def _render_table_content(elements: List[RawElement], context_texts: List[str]) -> str:
    """
    Build a rich, structured text block for a table SCU.

    Structure:
      [TABLE DATA]
      <RawTable.to_text() — headers + labelled rows>

      [TABLE CONTEXT]
      Nearby caption/title text.
    """
    parts: List[str] = []

    for el in elements:
        if el.element_type == ElementType.TABLE and el.table:
            table_text = el.table.to_text()
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
                # Check proximity against any member of the cluster
                for member in cluster:
                    if _distance(el, member) < PROXIMITY_EMU:
                        cluster.append(el)
                        merged = True
                        break
                if merged:
                    break
            if not merged:
                clusters.append([el])

        return clusters
