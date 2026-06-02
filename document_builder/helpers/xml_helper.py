from typing import Any

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from lxml.etree import _Element  # type: ignore[attr-defined]
import io

from document_builder.helpers.number_formatter import parse_signed_number
from config.report_config import GREEN_FILL, GREEN_TEXT, RED_FILL, RED_TEXT


def goa(parent, tag: str) -> _Element:
    """Get first child with *tags* or create and append it"""
    child = parent.find(qn(tag))
    if child is None:
        child = OxmlElement(tag)
        parent.append(child)
    return child


def shading(fill: str) -> _Element:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    shading.set(qn("w:val"), "clear")
    return shading


def remove_table_borders(table: Table) -> None:
    tblPr = goa(table._tbl, "w:tblPr")
    for existing in tblPr.findall(qn("w:tblBorders")):
        tblPr.remove(existing)
    tblBorders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "none")
        tblBorders.append(el)
    tblPr.append(tblBorders)


def set_table_full_width(table: Table) -> None:
    tblPr = goa(table._tbl, "w:tblPr")
    for existing in tblPr.findall(qn("w:tblW")):
        tblPr.remove(existing)
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), "5000")
    tblW.set(qn("w:type"), "pct")
    tblPr.append(tblW)


def set_cell_margins(
    cell, top: int = 80, bottom: int = 80, left: int = 120, right: int = 120
) -> None:
    tcPr = goa(cell._tc, "w:tcPr")
    for existing in tcPr.findall(qn("w:tcMar")):
        tcPr.remove(existing)
    tcMar = OxmlElement("w:tcMar")
    for name, val in (
        ("top", top),
        ("bottom", bottom),
        ("left", left),
        ("right", right),
    ):
        node = OxmlElement(f"w:{name}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def set_cell_borders(cell, sides: dict[str, str]) -> None:
    """sides: dict of side -> hex color, e.g. {"bottom" : "#000F47"}"""
    tcPr = goa(cell._tc, "w:tcPr")
    for existing in tcPr.findall(qn("w:tcBorders")):
        tcPr.remove(existing)
    tcBorders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        if side in sides:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "6")
            el.set(qn("w:color"), sides[side])
        else:
            el.set(qn("w:val"), "none")
        tcBorders.append(el)
    tcPr.append(tcBorders)


def set_row_height(row, height_twips: int) -> None:
    trPr = goa(row._tr, "w:trPr")
    trHeight = OxmlElement("w:trHeight")
    trHeight.set(qn("w:val"), str(height_twips))
    trHeight.set(qn("w:hRule"), "exact")
    trPr.append(trHeight)


def add_paragraph_bottom_rule(paragraph, color: str = "#D0D8E8", size: int = 4) -> None:
    pPr = goa(paragraph._p, "w:pPr")
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def set_paragraph_shading(paragraph, fill: str) -> None:
    pPr = goa(paragraph._p, "w:pPr")
    for existing in pPr.findall(qn("w:shd")):
        pPr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    pPr.append(shd)


def apply_delta_shading(cell, raw_value: Any, good_when_positive: bool = True) -> None:
    n = parse_signed_number(
        raw_value if isinstance(raw_value, (int, float)) else cell.text
    )
    if n is None or n == 0:
        return
    is_good = (n > 0) if good_when_positive else (n < 0)
    fill = GREEN_FILL if is_good else RED_FILL
    text_color = GREEN_TEXT if is_good else RED_TEXT
    goa(cell._tc, "w:tcPr").append(shading(fill))
    for p in cell.paragraphs:
        for run in p.runs:
            run.font.color.rgb = text_color
            run.bold = True
