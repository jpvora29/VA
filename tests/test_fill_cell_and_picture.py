"""The two generic capabilities the Carrier Survey page needs from the fill engine:
painting table-cell backgrounds, and swapping a picture's image for a rendered one.

Hermetic — builds its own one-slide deck, so it proves the mechanics without a template.
"""
from __future__ import annotations

import base64
import io

import pytest
from pptx import Presentation
from pptx.util import Inches

from studio.template_fill import fill as F

# Two valid, distinct 1x1 PNGs. Inline rather than drawn with Pillow: Pillow is only a
# transitive dependency here, and the test needs nothing more than "two different PNGs".
_RED = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
_BLUE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.fixture
def deck():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(2))
    picture = slide.shapes.add_picture(io.BytesIO(_RED), Inches(1), Inches(4),
                                       Inches(2), Inches(1))
    return prs, table.shape_id, picture.shape_id


def test_cell_background_is_painted_from_the_payload(deck):
    prs, table_id, _ = deck
    F._fill_cell_backgrounds(prs, {"cell_fills": {f"0:{table_id}": [
        {"r": 1, "c": 1, "hex": "CF3638"}]}})
    cell = prs.slides[0].shapes[0].table.cell(1, 1)
    assert str(cell.fill.fore_color.rgb) == "CF3638"


def test_a_none_hex_clears_the_cell_to_no_fill(deck):
    from pptx.enum.dml import MSO_FILL

    prs, table_id, _ = deck
    key = f"0:{table_id}"
    F._fill_cell_backgrounds(prs, {"cell_fills": {key: [{"r": 0, "c": 0, "hex": "008542"}]}})
    F._fill_cell_backgrounds(prs, {"cell_fills": {key: [{"r": 0, "c": 0, "hex": None}]}})
    assert prs.slides[0].shapes[0].table.cell(0, 0).fill.type == MSO_FILL.BACKGROUND


def test_an_out_of_range_cell_is_skipped_not_raised(deck):
    prs, table_id, _ = deck
    F._fill_cell_backgrounds(prs, {"cell_fills": {f"0:{table_id}": [
        {"r": 9, "c": 9, "hex": "CF3638"}]}})   # must not raise


def test_no_payload_is_a_no_op(deck):
    prs, _, _ = deck
    F._fill_cell_backgrounds(prs, {})           # must not raise


def test_picture_blob_is_replaced_in_place(deck):
    prs, _, picture_id = deck
    before = prs.slides[0].shapes[1].image.blob
    replacement = _BLUE
    F._replace_pictures(prs, {"pictures": {f"0:{picture_id}": replacement}})
    after = prs.slides[0].shapes[1]
    assert after.image.blob == replacement
    assert after.image.blob != before


def test_picture_replacement_keeps_the_authored_frame(deck):
    prs, _, picture_id = deck
    shape = prs.slides[0].shapes[1]
    frame = (shape.left, shape.top, shape.width, shape.height)
    F._replace_pictures(prs, {"pictures": {f"0:{picture_id}": _BLUE}})
    after = prs.slides[0].shapes[1]
    assert (after.left, after.top, after.width, after.height) == frame


def test_think_cell_object_is_removed_from_a_refilled_slide(deck):
    prs, _, picture_id = deck
    slide = prs.slides[0]
    box = slide.shapes.add_textbox(Inches(0), Inches(0), Inches(1), Inches(1))
    box.name = "think-cell data - do not delete"
    F._replace_pictures(prs, {"pictures": {f"0:{picture_id}": _BLUE}})
    assert not [s for s in slide.shapes if "think-cell" in s.name.lower()]


def test_think_cell_survives_a_slide_we_did_not_refill(deck):
    prs, _, _ = deck
    box = prs.slides[0].shapes.add_textbox(Inches(0), Inches(0), Inches(1), Inches(1))
    box.name = "think-cell data - do not delete"
    F._replace_pictures(prs, {"pictures": {}})
    assert [s for s in prs.slides[0].shapes if "think-cell" in s.name.lower()]
