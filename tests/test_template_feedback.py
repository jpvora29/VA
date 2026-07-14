"""Feedback/quadrant/highlights table fill — detection, roles and value composition.

Hermetic: the detection/composition tests run on synthetic ``Template`` objects with the
compute layer stubbed; the bubble-chart test runs against the real country template when
present (skip otherwise). ``STUDIO_AI=off`` keeps every path deterministic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from studio import compute as C
from studio.template_fill import feedback as F
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Slide, Template


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setenv("STUDIO_AI", "off")


# ── synthetic template (the product feedback page + the country quadrant page) ─


def _feedback_table() -> Shape:
    return Shape(shape_id=2, name="Table 1", kind="table", table=[
        ["", "What’s working well", "What’s not", "Growth Opportunities", "", ""],
        ["Country / Region(1)", "Relationship: …………", "", "",
         "$xxx.xM (+x.x%▲)\nMarsh GWP", "$xx.xM (-x.x▼)\nCarrier GWP"],
        ["", "", "", "", "x (=0►)\nCarrier Rank", "x.x% (+x.x%▲)\nCarrier SoW"],
        ["Country / Region (2)", "", "", ".",
         "$xxx.xM (+x.x%▲) Marsh GWP", "$xx.xM (-x.x▼)\nCarrier GWP"],
        ["", "", "", "", "x (+x▲)\nCarrier Rank", "x.x% (-x.x▼)\nCarrier SoW"],
    ])


def _quadrant_table() -> Shape:
    return Shape(shape_id=4, name="Table 3", kind="table", table=[
        ["Successes", "Challenges", "Opportunities for 2026", "Key Messages"],
        ["Performance", ". ", "", ""],
    ])


def _highlights_table() -> Shape:
    return Shape(shape_id=3, name="Table 2", kind="table", table=[["Key Highlights:"]])


def _template() -> Template:
    return Template(path="synthetic", width_emu=12192000, height_emu=6858000, slides=[
        Slide(index=0, layout="", shapes=[_feedback_table()]),
        Slide(index=1, layout="", shapes=[_quadrant_table(), _highlights_table()]),
    ])


_FACTS = {
    "carrier": {"current": 48e6, "pct": 52.5},
    "marsh": {"current": 411e6, "pct": 9.8},
    "rank": {"current": 2, "delta": 4},
    "sow": {"current": 11.6, "delta": 3.2},
}


def _result():
    return C.OverallResult(subject="ACME", flow="gpr",
                           resolved_filters={"Carrier_Group": "ACME", "Year": 2025})


@pytest.fixture
def _stub_compute(monkeypatch):
    monkeypatch.setattr(F, "_reporting_filters", lambda r: dict(r.resolved_filters))
    monkeypatch.setattr(F, "_countries_in_scope", lambda r: ["Japan"])
    monkeypatch.setattr(F, "_facts", lambda r, f: _FACTS)


# ── detection + role binding ──────────────────────────────────────────────────


def test_augment_binds_feedback_quadrant_and_highlight_cells():
    bindings = F.augment(_template(), [])
    roles = {b.role for b in bindings}
    # Country (1) block: 3 commentary columns (fbnote:) + 4 KPI callouts (fb:).
    assert {"fbnote:0:2:1:1", "fbnote:0:2:1:2", "fbnote:0:2:1:3",
            "fb:0:2:1:4", "fb:0:2:1:5", "fb:0:2:2:4", "fb:0:2:2:5"} <= roles
    # Country (2) block binds too, plus the quadrant row and the highlights cell.
    assert {"fb:0:2:3:4", "fbnote:1:4:1:0", "fbnote:1:4:1:3", "fbnote:1:3:0:0"} <= roles
    assert all(not b.placeholder for b in bindings)


def test_augment_rebinds_existing_manifest_slots_in_place():
    from studio.template_fill.slots import Slot

    existing = R.Binding(Slot(0, 2, ["cell", 1, 4], "$xxx.xM", "money", ""), None, True)
    out = F.augment(_template(), [existing])
    assert existing.role == "fb:0:2:1:4" and existing.placeholder is False
    assert existing in out


def test_augment_ignores_unrelated_tables():
    plain = Template(path="p", width_emu=1, height_emu=1, slides=[
        Slide(index=0, layout="", shapes=[Shape(shape_id=9, name="T", kind="table",
                                                table=[["A", "B"], ["1", "2"]])]),
    ])
    assert F.augment(plain, []) == []


# ── value composition (numbers on the page) ───────────────────────────────────


def test_values_fill_kpi_cells_in_template_style(_stub_compute):
    vals = F.values(_template(), _result())
    assert vals["fb:0:2:1:4"] == "$411M (+9.8%▲)\nMarsh GWP"
    assert vals["fb:0:2:1:5"] == "$48M (+52.5%▲)\nCarrier GWP"
    assert vals["fb:0:2:2:4"] == "2 (+4▲)\nCarrier Rank"
    assert vals["fb:0:2:2:5"] == "11.6% (+3.2%▲)\nCarrier SoW"


def test_values_blank_country_rows_beyond_scope(_stub_compute):
    # Only one country in scope → the Country (2) block is blanked entirely.
    vals = F.values(_template(), _result())
    assert vals["fb:0:2:3:4"] == "" and vals["fb:0:2:4:5"] == ""


def test_values_commentary_carries_figures(_stub_compute):
    vals = F.values(_template(), _result())
    assert "+52.5%" in vals["fbnote:0:2:1:1"] and "$48M" in vals["fbnote:0:2:1:1"]  # working well
    assert "$363M" in vals["fbnote:0:2:1:3"]                                        # headroom
    assert vals["fbnote:1:3:0:0"].startswith("Key Highlights:")
    assert "rank #2" in vals["fbnote:1:4:1:3"]                                      # key messages


def test_declines_flow_to_challenges():
    facts = {"carrier": {"current": 30e6, "pct": -12.0}, "marsh": {"current": 100e6, "pct": 2.0},
             "rank": {"current": 6, "delta": -2}, "sow": {"current": 4.0, "delta": -1.1}}
    text = F._challenges_text(facts)
    assert "-12.0%" in text and "slipped" in text
    assert F._kpi_cell("rank", facts) == "6 (-2▼)\nCarrier Rank"


def test_commentary_written_in_consistent_arial_11(tmp_path):
    # Commentary inherits ad-hoc template run formatting (18pt here, 10pt there) —
    # every note:/fbnote: write must come out Arial 11, KPI cells keep their own style.
    from pptx import Presentation
    from pptx.util import Inches, Pt

    from studio.template_fill.fill import fill_template
    from studio.template_fill.slots import Slot

    src = str(tmp_path / "t.pptx")
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    tb = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    tb.text_frame.text = "…………"
    tb.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    frame = slide.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(6), Inches(2))
    frame.table.rows[1].cells[1].text = "…………"
    tb_id, tbl_id = tb.shape_id, frame.shape_id
    prs.save(src)

    note_role, cell_role = f"note:0:{tb_id}:0", f"fbnote:0:{tbl_id}:1:1"
    manifest = [
        R.Binding(Slot(0, tb_id, ["para", 0], "…………", "text", ""), note_role, False).to_dict(),
        R.Binding(Slot(0, tbl_id, ["cell", 1, 1], "…………", "text", ""), cell_role, False).to_dict(),
    ]
    doc = {"template_path": src, "manifest": manifest,
           "values": {note_role: "Growth of +5.0% YoY.", cell_role: "Line one.\nLine two."},
           "overrides": {}, "map_overrides": {}, "added": {}}
    out = fill_template(doc, out_path=str(tmp_path / "styled.pptx"))

    prs2 = Presentation(out)
    shapes = {sh.shape_id: sh for sh in prs2.slides[0].shapes}
    note_runs = [r for p in shapes[tb_id].text_frame.paragraphs for r in p.runs if r.text]
    cell_runs = [r for p in shapes[tbl_id].table.rows[1].cells[1].text_frame.paragraphs
                 for r in p.runs if r.text]
    assert note_runs and cell_runs
    for run in note_runs + cell_runs:
        assert run.font.name == "Arial" and run.font.size.pt == 11


# ── the real bubble chart (native fill after detaching the think-cell link) ───


COUNTRY_TEMPLATE = "template/country_template.pptx"


def test_bubble_chart_filled_from_growth_points(tmp_path):
    if not Path(COUNTRY_TEMPLATE).exists():
        pytest.skip("country template not present")
    from pptx import Presentation

    from studio.template_fill.fill import fill_template

    points = [{"lob": "Property", "carrier_yoy": 12.0, "marsh_yoy": 5.0, "size": 40e6},
              {"lob": "Cyber", "carrier_yoy": -3.0, "marsh_yoy": 8.0, "size": 15e6}]
    doc = {"template_path": COUNTRY_TEMPLATE, "manifest": [],
           "values": {"growth_bubble": {"points": points}},
           "overrides": {}, "map_overrides": {}, "added": {}}
    out = fill_template(doc, out_path=str(tmp_path / "bubble.pptx"))

    prs = Presentation(out)
    charts = [sh.chart for s in prs.slides for sh in s.shapes if getattr(sh, "has_chart", False)]
    bubble = next(c for c in charts if "BUBBLE" in str(c.chart_type))
    assert [s.name for s in bubble.plots[0].series] == ["Property", "Cyber"]
    assert list(bubble.plots[0].series[0].values) == [12.0 / 100.0]
    assert bubble.has_legend
    # The hand-placed labels for the authored dummy bubbles are blanked.
    slide = next(s for s in prs.slides
                 for sh in s.shapes if getattr(sh, "has_chart", False) and sh.chart is bubble)
    texts = [sh.text_frame.text.strip() for sh in slide.shapes
             if getattr(sh, "has_text_frame", False)]
    assert "Property" not in texts and "FINPRO" not in texts
