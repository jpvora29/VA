from pathlib import Path
from pandas._typing import DtypeArg
from docx.shared import Inches, Mm, Pt, RGBColor

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

HEADING_FONT: str = "Georgia Pro Light"
BODY_FONT: str = "Arial"

HEADING_SIZE: Pt = Pt(28)
SUBHEADING_SIZE: Pt = Pt(18)
BODY_SIZE: Pt = Pt(10)
CAPTION_SIZE: Pt = Pt(7)
HEADER_FOOTER_SIZE: Pt = Pt(8)

BODY_TEXT_SPACE_BEFORE = Pt(10)
BODY_TEXT_SPACE_AFTER = Pt(10)


# ─── Color ─────────────────────────────────────────────────────────────────

NAVY: RGBColor = RGBColor(0, 15, 71)
LIGHT_BLUE: RGBColor = RGBColor(130, 186, 255)
GREY: RGBColor = RGBColor(143, 143, 143)
ELECTRIC_BLUE: RGBColor = RGBColor(11, 75, 255)
WHITE: RGBColor = RGBColor(255, 255, 255)
DARK = RGBColor(30, 40, 58)

GREEN_TEXT = RGBColor(46, 125, 50)
RED_TEXT = RGBColor(197, 53, 50)


LIGHT_GRAY = RGBColor(185, 182, 177)
GRAY = RGBColor(80, 95, 115)

GREEN_FILL = "#E8F5E9"
RED_FILL = "#FDECEA"

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
}
