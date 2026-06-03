from pathlib import Path
from pandas._typing import DtypeArg
from docx.shared import Inches, Mm, Pt, RGBColor

# The pitch report's palette + fonts are sourced from the authoritative design
# skill (document_builder/skills/pitch_report_design.md) so the .docx follows the
# skill. The loader has hardcoded fallbacks equal to the historical values, so
# this never changes existing output unless the skill is edited.
from document_builder.helpers.design_spec import load_design_spec

_SPEC = load_design_spec()

# ─── Page Layout ─────────────────────────────────────────────────────────────

PAGE_HEIGHT: Mm = Mm(297)
PAGE_WIDTH: Mm = Mm(210)
MARGIN_LEFT: Mm = Mm(20.574)
MARGIN_RIGHT: Mm = Mm(20.574)
MARGIN_TOP: Mm = Mm(20.574)
MARGIN_BOTTOM: Mm = Mm(20.574)

# Usable content width after margins (approximate, used for images & tab stops)
CONTENT_WIDTH: Inches = Inches(6.67)


# ─── Typography ───────────────────────────────────────────────────────────────

HEADING_FONT: str = _SPEC.font("heading")
BODY_FONT: str = _SPEC.font("body")

HEADING_SIZE: Pt = Pt(28)
SUBHEADING_SIZE: Pt = Pt(18)
BODY_SIZE: Pt = Pt(10)
CAPTION_SIZE: Pt = Pt(7)
HEADER_FOOTER_SIZE: Pt = Pt(8)

BODY_TEXT_SPACE_BEFORE = Pt(10)
BODY_TEXT_SPACE_AFTER = Pt(10)


# ─── Color ─────────────────────────────────────────────────────────────────

NAVY: RGBColor = _SPEC.rgb("navy")
LIGHT_BLUE: RGBColor = _SPEC.rgb("light_blue")
GREY: RGBColor = RGBColor(143, 143, 143)  # legacy neutral; not part of the brand palette
ELECTRIC_BLUE: RGBColor = _SPEC.rgb("electric_blue")
WHITE: RGBColor = _SPEC.rgb("white")
DARK = _SPEC.rgb("dark")

GREEN_TEXT = _SPEC.rgb("green_text")
RED_TEXT = _SPEC.rgb("red_text")


LIGHT_GRAY = _SPEC.rgb("light_gray")
GRAY = _SPEC.rgb("gray")

GREEN_FILL = _SPEC.hex_hash("green_fill")
RED_FILL = _SPEC.hex_hash("red_fill")

# Hex strings used in background shapes (no leading #)
COVER_BG_HEX: str = "CEECFF"


# Chart Font Color
CHART_FONT_COLOR: str = "#000F47"
CHART_FONT: str = "Arial"


SECTION_HEADINGS = {
    "executive summary",
    "carrier performance",
    "carrier comparison with peers/market",
    "swot analysis",
    "recommended close",
    "introduction",
    "key evidence",
    "proposed next steps",
    "conclusion",
    "key business drivers",
    "product-level analysis",
    "product level analysis",
    "carrier comparison with peers",
    "carrier comparison with top 5 carriers",
    "whitespace analysis",
    "industry-level analysis",
    "industry level analysis",
    "segment analysis",
    "segment-level analysis",
}
