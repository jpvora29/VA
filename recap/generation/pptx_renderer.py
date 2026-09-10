"""
recap/pptx_renderer.py

Populates the QBR Recap Template.pptx with a RecapOutput to produce
the final presentation-ready recap slide deck.

Template structure (from shape inspection):
--------------------------------------------
Slide 1 — Main Recap
  "Title 2"            (PH TITLE)  -> recap title
  "Text Placeholder 5" (PH BODY)   -> executive summary
  "TextBox 3"                       -> key themes / takeaways (left panel)
  "TextBox 9"                       -> action items (right panel)

Slide 2 — Country Feedback
  "Title 2"            (PH TITLE)  -> country slide title
  "TextBox 1"                       -> country feedback body

Usage
-----
from recap.generation.pptx_renderer import PPTXRenderer
from recap.config import settings

renderer = PPTXRenderer(template_path=settings.default_template_path)
out_path = renderer.render(recap, output_path="outputs/Q2_2026_recap.pptx")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from pptx import Presentation
from pptx.util import Pt
from lxml import etree
from pptx.oxml.ns import qn

from recap.schemas.recap import RecapOutput, ActionItemSummary, TitledTakeaway, CountrySummary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shape name constants (match the template exactly)
# ---------------------------------------------------------------------------
_S1_TITLE_NAME    = "Title 2"
_S1_EXEC_SUM_NAME = "Text Placeholder 5"
_S1_THEMES_NAME   = "TextBox 3"
_S1_ACTIONS_NAME  = "TextBox 9"
_S2_TITLE_NAME    = "Title 2"
_S2_BODY_NAME     = "TextBox 1"


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------

def _find_shape(slide, name: str):
    """Return the first shape whose name matches, or None."""
    for shape in slide.shapes:
        if shape.name == name:
            return shape
    return None


def _clear_text_frame(shape) -> None:
    """Remove all paragraph nodes from a text frame's txBody."""
    if not shape.has_text_frame:
        return
    txBody = shape.text_frame._txBody
    for p in txBody.findall(qn("a:p")):
        txBody.remove(p)


# ---------------------------------------------------------------------------
# XML text sanitiser
# ---------------------------------------------------------------------------
import re as _re

def _sanitise(text: str) -> str:
    """Strip NULL bytes and XML 1.0 illegal control characters from text."""
    if not text:
        return text
    # Remove NULL bytes
    text = text.replace("\x00", "")
    # Remove XML 1.0 illegal control chars (all C0 except \t \n \r, plus \x7f, C1 block)
    text = _re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    return text


def _set_single_para(shape, text: str,
                     font_size_pt: Optional[float] = None) -> None:
    """Replace text frame content with a single paragraph/run."""
    if not shape.has_text_frame:
        return
    shape.text_frame.word_wrap = True
    _clear_text_frame(shape)
    txBody = shape.text_frame._txBody
    p = etree.SubElement(txBody, qn("a:p"))
    r = etree.SubElement(p, qn("a:r"))
    attrib: dict = {"lang": "en-GB", "dirty": "0"}
    if font_size_pt:
        attrib["sz"] = str(int(font_size_pt * 100))
    etree.SubElement(r, qn("a:rPr"), attrib=attrib)
    t_elem = etree.SubElement(r, qn("a:t"))
    t_elem.text = _sanitise(text)


def _set_multiline(shape, lines: List[str],
                   font_size_pt: Optional[float] = None) -> None:
    """
    Write multiple lines into a text frame, one paragraph per line.
    Captures the template's existing font size so styling is preserved.
    """
    if not shape.has_text_frame:
        return
    shape.text_frame.word_wrap = True

    # Capture existing font size from template XML
    existing_sz: Optional[str] = None
    try:
        for rPr_el in shape.text_frame._txBody.findall(".//" + qn("a:rPr")):
            sz = rPr_el.get("sz")
            if sz:
                existing_sz = sz
                break
    except Exception:
        pass

    _clear_text_frame(shape)
    txBody = shape.text_frame._txBody
    use_sz = str(int(font_size_pt * 100)) if font_size_pt else existing_sz

    for line in lines:
        p = etree.SubElement(txBody, qn("a:p"))
        r = etree.SubElement(p, qn("a:r"))
        attrib: dict = {"lang": "en-GB", "dirty": "0"}
        if use_sz:
            attrib["sz"] = use_sz
        etree.SubElement(r, qn("a:rPr"), attrib=attrib)
        t_elem = etree.SubElement(r, qn("a:t"))
        t_elem.text = _sanitise(line)


# ---------------------------------------------------------------------------
# Content formatters
# ---------------------------------------------------------------------------

def _set_key_themes(shape, recap: RecapOutput) -> None:
    """Write key takeaway bullets into a text frame.

    Each bullet is one paragraph with two runs:
      Run 1 — bold:   "• Title: "
      Run 2 — normal: narrative sentence

    This mirrors the two-run pattern used for country feedback so the
    title is visually distinct without requiring a separate shape.
    """
    if not shape.has_text_frame:
        return
    shape.text_frame.word_wrap = True

    # Capture existing font size from template XML
    existing_sz: Optional[str] = None
    try:
        for rPr_el in shape.text_frame._txBody.findall(".//" + qn("a:rPr")):
            sz = rPr_el.get("sz")
            if sz:
                existing_sz = sz
                break
    except Exception:
        pass

    _clear_text_frame(shape)
    txBody = shape.text_frame._txBody

    if not recap.key_takeaways:
        p = etree.SubElement(txBody, qn("a:p"))
        r = etree.SubElement(p, qn("a:r"))
        rPr_attrib: dict = {"lang": "en-GB", "dirty": "0"}
        if existing_sz:
            rPr_attrib["sz"] = existing_sz
        etree.SubElement(r, qn("a:rPr"), attrib=rPr_attrib)
        t = etree.SubElement(r, qn("a:t"))
        t.text = "(No key takeaways generated.)"
        return

    for idx, takeaway in enumerate(recap.key_takeaways):
        p = etree.SubElement(txBody, qn("a:p"))

        # Run 1 — bold title
        r1 = etree.SubElement(p, qn("a:r"))
        rPr1: dict = {"lang": "en-GB", "dirty": "0", "b": "1"}
        if existing_sz:
            rPr1["sz"] = existing_sz
        etree.SubElement(r1, qn("a:rPr"), attrib=rPr1)
        t1 = etree.SubElement(r1, qn("a:t"))
        t1.text = _sanitise(f"\u2022 {takeaway.title}: ")

        # Run 2 — normal weight narrative
        r2 = etree.SubElement(p, qn("a:r"))
        rPr2: dict = {"lang": "en-GB", "dirty": "0", "b": "0"}
        if existing_sz:
            rPr2["sz"] = existing_sz
        etree.SubElement(r2, qn("a:rPr"), attrib=rPr2)
        t2 = etree.SubElement(r2, qn("a:t"))
        t2.text = _sanitise(takeaway.narrative)

        # Blank separator paragraph between bullets (except after last)
        if idx < len(recap.key_takeaways) - 1:
            blank_p = etree.SubElement(txBody, qn("a:p"))
            blank_r = etree.SubElement(blank_p, qn("a:r"))
            blank_rPr: dict = {"lang": "en-GB", "dirty": "0"}
            if existing_sz:
                blank_rPr["sz"] = existing_sz
            etree.SubElement(blank_r, qn("a:rPr"), attrib=blank_rPr)
            etree.SubElement(blank_r, qn("a:t")).text = ""


def _format_actions(action_items: List[ActionItemSummary]) -> List[str]:
    """Build the Actions lines for Slide 1 right panel.

    Already capped to top 3-4 by RecapGenerator.
    Each item is rendered as one bullet line (prefixed with "• ", matching
    the bullet style used for key takeaways and country feedback) — owner,
    deadline, and LoB are woven into the action sentence by the ranker LLM
    so no separate meta sub-line is needed.
    """
    if not action_items:
        return ["(No action items identified.)"]
    lines: List[str] = []
    for ai in action_items:
        lines.append(f"\u2022 {ai.action}")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _add_country_paragraph(txBody, country: str, summary: str,
                            sz: Optional[str]) -> None:
    """
    Append one paragraph to txBody for a country block.

    Format:
      <Country name (bold, amber)>: <summary text (white)>

    The country name and colon are one run (bold, amber #E8A000);
    the summary text is a second run (regular weight, white).
    """
    # Amber colour matching the image — close to Marsh gold #E8A000
    _AMBER = "E8A000"
    _WHITE = "FFFFFF"

    p = etree.SubElement(txBody, qn("a:p"))

    # Run 1 — bold amber country label + colon
    r1 = etree.SubElement(p, qn("a:r"))
    rPr1_attrib: dict = {"lang": "en-GB", "dirty": "0", "b": "1"}
    if sz:
        rPr1_attrib["sz"] = sz
    rPr1 = etree.SubElement(r1, qn("a:rPr"), attrib=rPr1_attrib)
    # Solid fill with amber colour
    solidFill1 = etree.SubElement(rPr1, qn("a:solidFill"))
    srgb1 = etree.SubElement(solidFill1, qn("a:srgbClr"))
    srgb1.set("val", _AMBER)
    t1 = etree.SubElement(r1, qn("a:t"))
    t1.text = _sanitise(f"{country}: ")

    # Run 2 — white summary text
    r2 = etree.SubElement(p, qn("a:r"))
    rPr2_attrib: dict = {"lang": "en-GB", "dirty": "0", "b": "0"}
    if sz:
        rPr2_attrib["sz"] = sz
    rPr2 = etree.SubElement(r2, qn("a:rPr"), attrib=rPr2_attrib)
    solidFill2 = etree.SubElement(rPr2, qn("a:solidFill"))
    srgb2 = etree.SubElement(solidFill2, qn("a:srgbClr"))
    srgb2.set("val", _WHITE)
    t2 = etree.SubElement(r2, qn("a:t"))
    t2.text = _sanitise(summary)


def _set_country_feedback(shape, country_summaries: List[CountrySummary]) -> None:
    """
    Write per-country feedback into a text frame.

    Each country gets one paragraph:
      <Country (bold amber)>: <summary (white)>
    Blank paragraphs separate countries.
    The text frame's existing font size is preserved.
    """
    if not shape.has_text_frame:
        return
    shape.text_frame.word_wrap = True

    # Capture existing font size
    existing_sz: Optional[str] = None
    try:
        for rPr_el in shape.text_frame._txBody.findall(".//" + qn("a:rPr")):
            sz = rPr_el.get("sz")
            if sz:
                existing_sz = sz
                break
    except Exception:
        pass

    _clear_text_frame(shape)
    txBody = shape.text_frame._txBody

    for i, cs in enumerate(country_summaries):
        _add_country_paragraph(txBody, cs.country, cs.summary, existing_sz)
        # Blank separator between countries (except after the last one)
        if i < len(country_summaries) - 1:
            blank_p = etree.SubElement(txBody, qn("a:p"))
            blank_r = etree.SubElement(blank_p, qn("a:r"))
            blank_rPr_attrib: dict = {"lang": "en-GB", "dirty": "0"}
            if existing_sz:
                blank_rPr_attrib["sz"] = existing_sz
            etree.SubElement(blank_r, qn("a:rPr"), attrib=blank_rPr_attrib)
            blank_t = etree.SubElement(blank_r, qn("a:t"))
            blank_t.text = ""


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class PPTXRenderer:
    """
    Clones the QBR Recap Template.pptx and populates it with a
    RecapOutput to produce the final presentation-ready file.

    Parameters
    ----------
    template_path : Path to QBR Recap Template.pptx.
                    Defaults to assets/QBR Recap Template.pptx relative
                    to the package root when not supplied.
    """

    def __init__(self, template_path: Optional[str | Path] = None) -> None:
        if template_path is None:
            template_path = (
                Path(__file__).parent.parent / "assets" / "QBR Recap Template.pptx"
            )
        self.template_path = Path(template_path)
        if not self.template_path.exists():
            raise FileNotFoundError(
                f"QBR Recap Template not found: {self.template_path}\n"
                "Copy QBR Recap Template.pptx into assets/ or pass "
                "template_path= explicitly to PPTXRenderer."
            )

    def render(
        self,
        recap: RecapOutput,
        output_path: Optional[str | Path] = None,
        slide1_title: Optional[str] = None,
        slide2_title: Optional[str] = None,
    ) -> Path:
        """
        Populate the template with recap content and save to disk.

        Parameters
        ----------
        recap          : RecapOutput from the pipeline.
        output_path    : Where to save the .pptx.
                         Defaults to outputs/<deck_id>_recap.pptx.
        slide1_title   : Override for slide 1 title.
        slide2_title   : Override for slide 2 title.

        Returns
        -------
        Path of the saved .pptx file.
        """
        prs = Presentation(str(self.template_path))

        client   = recap.client_name  or ""
        period   = recap.period_label or ""
        s1_title = slide1_title or "  |  ".join(
            p for p in [client, period, "QBR Recap"] if p
        )
        s2_title = slide2_title or "  |  ".join(
            p for p in [period, "Country Feedback Summary"] if p
        )

        # ── Slide 1: Main Recap ───────────────────────────────────────
        slide1 = prs.slides[0]

        shape = _find_shape(slide1, _S1_TITLE_NAME)
        if shape:
            _set_single_para(shape, s1_title)
        else:
            logger.warning("Slide 1: shape %r not found", _S1_TITLE_NAME)

        shape = _find_shape(slide1, _S1_EXEC_SUM_NAME)
        if shape:
            _set_single_para(shape, recap.executive_summary)
        else:
            logger.warning("Slide 1: shape %r not found", _S1_EXEC_SUM_NAME)

        shape = _find_shape(slide1, _S1_THEMES_NAME)
        if shape:
            _set_key_themes(shape, recap)
        else:
            logger.warning("Slide 1: shape %r not found", _S1_THEMES_NAME)

        shape = _find_shape(slide1, _S1_ACTIONS_NAME)
        if shape:
            _set_multiline(shape, _format_actions(recap.action_items))
        else:
            logger.warning("Slide 1: shape %r not found", _S1_ACTIONS_NAME)

        # ── Slide 2: Country Feedback ─────────────────────────────────
        slide2 = prs.slides[1]

        if recap.country_summaries:
            shape = _find_shape(slide2, _S2_TITLE_NAME)
            if shape:
                _set_single_para(shape, s2_title)
            else:
                logger.warning("Slide 2: shape %r not found", _S2_TITLE_NAME)

            shape = _find_shape(slide2, _S2_BODY_NAME)
            if shape:
                _set_country_feedback(shape, recap.country_summaries)
            else:
                logger.warning("Slide 2: shape %r not found", _S2_BODY_NAME)
        else:
            logger.info(
                "Slide 2 (Country Feedback) skipped — fewer than 2 unique countries."
            )

        # ── Save ──────────────────────────────────────────────────────
        if output_path is None:
            out_dir = Path("outputs")
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = "_".join(p for p in [recap.deck_id, "recap"] if p) + ".pptx"
            output_path = out_dir / fname

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(output_path))
        logger.info("Recap PPTX saved: %s", output_path)
        return output_path
