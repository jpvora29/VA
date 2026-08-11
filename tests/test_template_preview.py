from __future__ import annotations

from studio.page import template_preview as TP
from studio.template_fill.analyze import Slide, Template


def test_template_preview_uses_cached_background_without_rendering(monkeypatch):
    template = Template(
        path="assembled.pptx",
        width_emu=12192000,
        height_emu=6858000,
        slides=[Slide(index=0, layout="blank")],
    )
    monkeypatch.setattr(TP.registry, "derive_manifest", lambda path: (template, []))
    monkeypatch.setattr(TP, "materialize_fields", lambda doc: {})
    monkeypatch.setattr(TP, "cached_doc_backgrounds", lambda doc, slide_count: ["/assets/cached.png"])

    body = TP.template_preview_body(
        {
            "template_path": "assembled.pptx",
            "values": {},
            "manifest": [],
            "hidden": [],
            "order": [0],
            "background_urls": ["/assets/pre-rendered.png"],
        },
        {"idx": 0},
    )

    stage = body.children[1].children[0].children
    assert stage.style["backgroundImage"] == "url('/assets/pre-rendered.png')"


# ── the survey table's band colours reach the on-screen preview ──────────────
#
# The Carrier Survey table says as much in its CELL COLOUR as in its numbers — each score's
# move against the previous survey, against the legend printed under it. The export writes
# them (`fill._fill_cell_backgrounds`), but the geometry preview rendered every table as
# plain text, so the slide on screen was a grid of bare numbers for a page that ships fully
# banded. "The background is not populating" was, on this path, literally true.


def _survey_table_shape(rows):
    from studio.template_fill.analyze import Shape

    return Shape(shape_id=49, name="scores", kind="table",
                 x=0, y=0, w=100, h=100, table=rows)


def test_the_preview_paints_the_cell_colours_the_export_writes():
    shape = _survey_table_shape([["Section", "Cyber"], ["Underwriting", "6.3"]])
    values = {"cell_fills": {"0:49": [{"r": 1, "c": 1, "hex": "CF3638"}]}}

    table = TP._table_shape(shape, {}, 0, {}, values)

    painted = [cell for row in table.children.children.children
               for cell in row.children if cell.style]
    assert len(painted) == 1
    assert painted[0].style["background"] == "#CF3638"
    assert painted[0].children == "6.3"


def test_a_cell_with_no_band_keeps_the_preview_s_own_styling():
    shape = _survey_table_shape([["Section", "Cyber"], ["Underwriting", "6.3"]])
    values = {"cell_fills": {"0:49": [{"r": 1, "c": 1, "hex": None}]}}

    table = TP._table_shape(shape, {}, 0, {}, values)

    assert not any(cell.style for row in table.children.children.children
                   for cell in row.children)


def test_a_table_with_no_payload_is_unchanged():
    shape = _survey_table_shape([["Section", "Cyber"], ["Underwriting", "6.3"]])
    for values in ({}, {"cell_fills": {"0:99": [{"r": 1, "c": 1, "hex": "CF3638"}]}}, None):
        table = TP._table_shape(shape, {}, 0, {}, values)
        assert not any(cell.style for row in table.children.children.children
                       for cell in row.children)
