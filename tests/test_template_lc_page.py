"""The LC-ranking page: panel detection, quadrant placement, and the written scatter.

Two layers:
  * unit — panel ordering and quadrant rules on an in-memory ``Template``, so the logic is
    pinned independently of any .pptx;
  * integration — the real ``template/product_template.pptx`` valued from the seed DB and
    then filled, proving a panel populates end-to-end and that the template's hand-drawn
    quadrant bands, fake axis and dummy point labels do not survive it.

Deterministic: seed DB, no LLM.
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from pptx import Presentation

from studio.compute import compute_overall
from studio.template_fill import lc_page as L
from studio.template_fill.analyze import Shape, Slide, Template, analyze

PRODUCT_TEMPLATE = "template/product_template.pptx"


def _scatter(shape_id: int, x: float, y: float) -> Shape:
    return Shape(shape_id=shape_id, name=f"Chart {shape_id}", kind="chart",
                 chart_type="XY_SCATTER (-4169)", x=x, y=y, w=6.0, h=1.8)


def _page(*charts: Shape) -> Template:
    title = Shape(shape_id=1, name="Title 1", kind="text",
                  paragraphs=["Marsh Portfolio and LC ranking"])
    return Template(path="synthetic", width_emu=12192000, height_emu=6858000,
                    slides=[Slide(index=0, layout="", shapes=[title, *charts])])


# ── panel detection ──────────────────────────────────────────────────────────


def test_panels_are_ordered_top_row_first_then_left_to_right():
    # Authored out of order, and with the two panels of a row a hair apart vertically —
    # a plain (y, x) sort would read that as four rows of one.
    page = _page(_scatter(40, x=6.8, y=4.29), _scatter(10, x=0.4, y=2.34),
                 _scatter(30, x=0.4, y=4.28), _scatter(20, x=6.8, y=2.35))
    assert [p.shape_id for p in L.panels(page)] == [10, 20, 30, 40]


def test_only_the_ranking_page_is_a_quadrant_panel():
    page = _page(_scatter(10, x=0.4, y=2.34))
    page.slides[0].shapes[0].paragraphs = ["Carrier vs Marsh growth rates"]
    assert L.panels(page) == []


def test_a_page_without_scatters_yields_no_panels():
    assert L.panels(_page()) == []


# ── quadrant placement ───────────────────────────────────────────────────────


@pytest.mark.parametrize("size,rank,expected", [
    (900, 2, L.LEAD),        # big pool, top-5 rank — the position to defend
    (100, 2, L.SOLID),       # small pool, top-5 rank
    (100, 9, L.MINOR),       # small pool, chased — least material
    (900, 9, L.GAP),         # big pool, chased — the opportunity
    (500, 5, L.LEAD),        # both thresholds are inclusive: rank 5 is still top-5…
    (500, 6, L.GAP),         # …and one place below is not
])
def test_quadrant_of_places_a_point(size, rank, expected):
    assert L.quadrant_of(size, rank, size_cut=500) == expected


# ── integration: the real template, valued from the seed DB ──────────────────


def _result(countries, product=None):
    from studio.template_fill.bindings import scope_to_product

    run = compute_overall(filters={"carrier": "Zurich", "country": countries, "year": 2025})
    run = replace(run, scope_countries=tuple(countries))
    return scope_to_product(run, product) if product else run


@pytest.fixture(scope="module")
def product_template():
    if not Path(PRODUCT_TEMPLATE).exists():
        pytest.skip("product template not present")
    return analyze(PRODUCT_TEMPLATE)


def test_every_panel_gets_a_payload_and_the_ones_in_scope_get_points(product_template):
    panels = L.values(product_template, _result(["Singapore", "Japan"]))["lc_quadrant"]
    assert len(panels) == len(L.panels(product_template)) == 4
    filled = [p for p in panels.values() if p["points"]]
    assert [p["country"] for p in filled] == ["Singapore", "Japan"]
    # The panels past the countries in scope carry no points — the fill engine blanks them
    # rather than shipping the template's authored example book under an erased title.
    assert [p["points"] for p in panels.values() if not p["country"]] == [[], []]


def test_points_carry_the_marsh_pool_the_carrier_rank_and_a_quadrant(product_template):
    panel = next(p for p in L.values(product_template, _result(["Singapore"]))["lc_quadrant"].values()
                 if p["points"])
    assert len(panel["points"]) > 1
    for point in panel["points"]:
        assert point["size"] > 0 and point["rank"] >= 1
        assert point["quadrant"] in {L.LEAD, L.SOLID, L.MINOR, L.GAP}
    # The size split is the MEDIAN of the lines plotted, so both sides are populated.
    sizes = sorted(p["size"] for p in panel["points"])
    assert sizes[0] < panel["size_cut"] <= sizes[-1]
    assert panel["rank_cut"] == L.RANK_CUT == 5


def test_a_product_subdeck_still_plots_the_whole_line_of_business_mix(product_template):
    # The page is a PORTFOLIO view: a per-product sub-deck's own pin must not collapse
    # every panel to the single dot of the product the sub-deck happens to be about.
    scoped = _result(["Singapore"], product="Property")
    panel = next(p for p in L.values(product_template, scoped)["lc_quadrant"].values()
                 if p["points"])
    names = {p["name"] for p in panel["points"]}
    assert len(names) > 1 and "Property" in names


# ── integration: the written chart ───────────────────────────────────────────


_LINES = [{"name": "Property", "size": 545e6, "rank": 6, "quadrant": L.GAP},
          {"name": "Cyber", "size": 300e6, "rank": 1, "quadrant": L.SOLID},
          {"name": "Financial Lines", "size": 414e6, "rank": 3, "quadrant": L.LEAD},
          {"name": "Marine", "size": 299e6, "rank": 7, "quadrant": L.MINOR}]


@pytest.fixture(scope="module")
def filled_page(tmp_path_factory):
    if not Path(PRODUCT_TEMPLATE).exists():
        pytest.skip("product template not present")
    from studio.template_fill.fill import fill_template

    panels = L.panels(analyze(PRODUCT_TEMPLATE))
    payload = {f"{p.slide_idx}:{p.shape_id}": {"country": None, "points": [],
                                               "rank_cut": 5, "size_cut": 0.0}
               for p in panels}
    payload[f"{panels[0].slide_idx}:{panels[0].shape_id}"] = {
        "country": "Singapore", "points": _LINES, "rank_cut": 5, "size_cut": 357e6}
    doc = {"template_path": PRODUCT_TEMPLATE, "manifest": [],
           "values": {"lc_quadrant": payload}, "overrides": {}, "map_overrides": {}, "added": {}}
    out = fill_template(doc, out_path=str(tmp_path_factory.mktemp("lc") / "lc.pptx"))
    return Presentation(out).slides[0], panels


def test_each_line_is_its_own_series_coloured_by_its_quadrant(filled_page):
    from pptx.dml.color import RGBColor

    slide, panels = filled_page
    chart = next(sh.chart for sh in slide.shapes
                 if getattr(sh, "has_chart", False) and int(sh.shape_id) == panels[0].shape_id)
    series = list(chart.plots[0].series)
    assert [s.name for s in series] == [line["name"] for line in _LINES]
    assert [list(s.values) for s in series] == [[float(l["rank"])] for l in _LINES]
    for ser, line in zip(series, _LINES):
        expected = RGBColor.from_string({"gap": "E6A09E", "solid": "DFECD7",
                                         "lead": "B0DC92", "minor": "F0C3C2"}[line["quadrant"]])
        assert ser.marker.format.fill.fore_color.rgb == expected
    # The point names its own quadrant, so there is no legend of four identical keys.
    assert not chart.has_legend
    assert '<c:showSerName val="1"/>' in chart._chartSpace.xml


def test_the_thresholds_are_drawn_as_the_axes_own_crossings(filled_page):
    slide, panels = filled_page
    chart = next(sh.chart for sh in slide.shapes
                 if getattr(sh, "has_chart", False) and int(sh.shape_id) == panels[0].shape_id)
    xml = chart._chartSpace.xml
    crossings = {m for m in re.findall(r'<c:crossesAt val="([^"]+)"/>', xml)}
    assert crossings == {"5", "3.57e+08"}       # top-5 rank, and the median portfolio size
    assert "<c:crosses " not in xml             # the authored "crosses at max" is gone
    assert '<c:numFmt formatCode="$#,##0,,&quot;M&quot;" sourceLinked="0"/>' in xml


def test_the_hand_drawn_quadrant_bands_and_fake_axis_do_not_survive(filled_page):
    slide, panels = filled_page
    chart = next(sh for sh in slide.shapes
                 if getattr(sh, "has_chart", False) and int(sh.shape_id) == panels[0].shape_id)
    left, right = chart.left, chart.left + chart.width
    over_panel = [sh for sh in slide.shapes
                  if sh.shape_id != chart.shape_id and sh.left is not None
                  and left <= sh.left + sh.width // 2 <= right
                  and chart.top <= sh.top + sh.height // 2 <= chart.top + chart.height]
    # Nothing hand-drawn is left inside the panel: no painted band group, no dashed
    # threshold line, no "$2,080M" tick faking a broken axis, no "Product (1)" label.
    assert not [sh for sh in over_panel if sh.shape_type in (5, 6, 9)]
    texts = [sh.text_frame.text for sh in over_panel if getattr(sh, "has_text_frame", False)]
    assert not [t for t in texts if "Product" in t or "$" in t]


def test_the_axis_captions_survive_a_filled_panel(filled_page):
    slide, _ = filled_page
    captions = [sh.text_frame.text.strip() for sh in slide.shapes
                if getattr(sh, "has_text_frame", False)]
    assert "Size of Marsh Portfolio" in captions      # describes the panel, not its data


def test_a_panel_with_no_country_is_removed_whole(filled_page):
    slide, panels = filled_page
    ids = {int(sh.shape_id) for sh in slide.shapes if getattr(sh, "has_chart", False)}
    assert panels[0].shape_id in ids
    assert not [p for p in panels[1:] if p.shape_id in ids]
