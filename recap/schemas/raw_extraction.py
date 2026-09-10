"""
schemas/raw_extraction.py

Source-of-truth representation of a PowerPoint deck.
Nothing in this layer should be mutated by downstream stages.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Element type vocabulary
# ---------------------------------------------------------------------------

class ElementType(str, Enum):
    TEXT_BOX       = "text_box"
    SHAPE          = "shape"
    TABLE          = "table"
    CHART          = "chart"
    IMAGE          = "image"
    GROUP          = "group"
    PLACEHOLDER    = "placeholder"
    CONNECTOR      = "connector"
    SMART_ART      = "smart_art"
    UNKNOWN        = "unknown"


# ---------------------------------------------------------------------------
# Table cell / table
# ---------------------------------------------------------------------------

class RawTableCell(BaseModel):
    row: int
    col: int
    text: str
    is_header: bool = False
    row_span: int = 1
    col_span: int = 1


class RawTable(BaseModel):
    rows: int
    cols: int
    cells: List[RawTableCell]

    def to_text(self) -> str:
        """
        Structured text representation that preserves row/column context.

        Format:
          Table (<rows> rows x <cols> cols)
          Headers: Col1 | Col2 | Col3
          Row 1:   Val1 | Val2 | Val3
          Row 2:   Val1 | Val2 | Val3
        """
        if not self.cells:
            return ""

        # Build a 2D grid
        grid: List[List[str]] = [
            [""] * self.cols for _ in range(self.rows)
        ]
        for cell in self.cells:
            if 0 <= cell.row < self.rows and 0 <= cell.col < self.cols:
                grid[cell.row][cell.col] = cell.text.strip()

        lines: List[str] = [f"Table ({self.rows} rows × {self.cols} cols)"]

        # Detect header row (row 0 is_header=True, or all caps / bold-like)
        header_row = grid[0] if self.rows > 0 else []
        if any(h for h in header_row):
            lines.append("  Headers: " + " | ".join(
                h if h else "(blank)" for h in header_row
            ))
            data_start = 1
        else:
            data_start = 0

        for ri in range(data_start, self.rows):
            row_cells = grid[ri]
            # Skip entirely blank rows
            if not any(c for c in row_cells):
                continue
            # Pair header label with value where possible
            if header_row and any(h for h in header_row):
                pairs = []
                for ci, val in enumerate(row_cells):
                    if ci < len(header_row) and header_row[ci]:
                        pairs.append(f"{header_row[ci]}: {val}" if val else "")
                    elif val:
                        pairs.append(val)
                line = "  | ".join(p for p in pairs if p)
            else:
                line = " | ".join(c for c in row_cells if c)
            if line.strip():
                lines.append(f"  Row {ri}: {line}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

class RawChartSeries(BaseModel):
    series_name: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    values: List[Any]   = Field(default_factory=list)


class RawChart(BaseModel):
    chart_type: Optional[str] = None
    title: Optional[str]      = None
    series: List[RawChartSeries] = Field(default_factory=list)
    has_data_labels: bool = False
    # Axis labels extracted from chart XML
    category_axis_label: Optional[str] = None   # e.g. "Country", "Quarter"
    value_axis_label: Optional[str]    = None   # e.g. "GWP (£m)", "% Growth"

    def to_text(self) -> str:
        """
        Produce a structured, axis-labelled text block so the LLM can
        understand what the chart is measuring and what the values mean.

        Format:
          Chart: <title>
          Type: <chart_type>
          X-axis (category): <category_axis_label>
          Y-axis (value):    <value_axis_label>
          Series — <name>: <cat>=<val>, <cat>=<val>, ...
        """
        lines: List[str] = []

        if self.title:
            lines.append(f"Chart: {self.title}")
        if self.chart_type:
            # Strip python-pptx enum prefix noise, e.g. "XL_CHART_TYPE.BAR_CLUSTERED"
            ct = self.chart_type.split(".")[-1].replace("_", " ").title()
            lines.append(f"Chart type: {ct}")
        if self.category_axis_label:
            lines.append(f"X-axis (category): {self.category_axis_label}")
        if self.value_axis_label:
            lines.append(f"Y-axis (value): {self.value_axis_label}")

        for s in self.series:
            name = s.series_name or "Series"
            if s.categories and s.values:
                # Pair up categories with values, skipping None values
                pairs = []
                for cat, val in zip(s.categories, s.values):
                    if val is None:
                        continue
                    # Format numeric values cleanly
                    try:
                        fval = float(val)
                        # Show as integer if whole number, else 2dp
                        vstr = str(int(fval)) if fval == int(fval) else f"{fval:.2f}"
                    except (TypeError, ValueError):
                        vstr = str(val)
                    pairs.append(f"{cat}: {vstr}")
                if pairs:
                    lines.append(f"  {name}: {', '.join(pairs)}")
            elif s.values:
                # No category labels — just list values
                vals = []
                for v in s.values:
                    if v is None:
                        continue
                    try:
                        fval = float(v)
                        vals.append(str(int(fval)) if fval == int(fval) else f"{fval:.2f}")
                    except (TypeError, ValueError):
                        vals.append(str(v))
                if vals:
                    lines.append(f"  {name}: {', '.join(vals)}")
            elif s.categories:
                # Categories only (e.g. a label-only chart)
                lines.append(f"  {name}: {', '.join(s.categories)}")

        return "\n".join(lines) if lines else ""


# ---------------------------------------------------------------------------
# Individual PPT element (text box, shape, image, etc.)
# ---------------------------------------------------------------------------

class RawElement(BaseModel):
    """
    Atomic PPT element — the immutable source-of-truth unit.
    Every downstream stage references elements by element_id.
    """

    element_id: str = Field(
        description="Unique ID within the deck, e.g. 'slide_03_shp_007'."
    )
    deck_id: str
    slide_number: int

    element_type: ElementType = ElementType.UNKNOWN
    shape_type: Optional[str] = Field(
        default=None,
        description="python-pptx MSO_SHAPE_TYPE string, if available.",
    )

    # --- Content ---
    text: Optional[str]       = None   # plain text, stripped
    alt_text: Optional[str]   = None   # image alt-text / title attribute
    table: Optional[RawTable] = None
    chart: Optional[RawChart] = None

    # --- Position (EMU units from python-pptx) ---
    x: Optional[int]      = None
    y: Optional[int]      = None
    width: Optional[int]  = None
    height: Optional[int] = None

    # --- Layout helpers ---
    reading_order: Optional[int] = Field(
        default=None,
        description="0-based reading order derived from top-left spatial sort.",
    )

    # --- Hierarchy ---
    parent_group_id: Optional[str] = Field(
        default=None,
        description="element_id of the parent group shape, if any.",
    )
    child_element_ids: List[str] = Field(
        default_factory=list,
        description="element_ids of direct children (for group shapes).",
    )

    # --- Formatting hints ---
    font_size: Optional[float]  = None   # points
    is_bold: Optional[bool]     = None
    is_italic: Optional[bool]   = None
    fill_color: Optional[str]   = None   # hex string if solid fill
    text_color: Optional[str]   = None

    # --- Misc ---
    hyperlink: Optional[str]    = None
    is_placeholder: bool        = False
    placeholder_type: Optional[str] = None   # e.g. 'TITLE', 'BODY', 'FOOTER'

    def effective_text(self) -> str:
        """Best available text representation of this element."""
        if self.text:
            return self.text
        if self.table:
            return self.table.to_text()
        if self.chart:
            return self.chart.to_text()
        if self.alt_text:
            return self.alt_text
        return ""


# ---------------------------------------------------------------------------
# Slide
# ---------------------------------------------------------------------------

class RawSlide(BaseModel):
    deck_id: str
    slide_number: int        # 1-based
    slide_id: str            # e.g. 'client_q2_2026_slide_03'
    title: Optional[str]     = None
    section: Optional[str]   = None   # section/group name if the deck uses sections

    elements: List[RawElement] = Field(default_factory=list)
    notes: Optional[str]       = None   # slide notes pane text

    layout_name: Optional[str] = None   # slide layout name, e.g. 'Two Content'


# ---------------------------------------------------------------------------
# Deck
# ---------------------------------------------------------------------------

class RawDeck(BaseModel):
    deck_id: str
    file_path: str

    meeting_date: Optional[str]     = None   # ISO-8601 date string, e.g. '2026-04-01'
    quarter: Optional[str]          = None   # e.g. 'Q2'
    half_year: Optional[str]        = None   # e.g. 'H1'
    year: Optional[int]             = None
    period_label: Optional[str]     = None   # free-form, e.g. 'Q2 2026 QBR'

    client_name: Optional[str]      = None
    company_name: Optional[str]     = None

    slides: List[RawSlide]          = Field(default_factory=list)

    # Deck-level section map: section_name → [slide_numbers]
    section_map: Dict[str, List[int]] = Field(default_factory=dict)

    @property
    def total_slides(self) -> int:
        return len(self.slides)
