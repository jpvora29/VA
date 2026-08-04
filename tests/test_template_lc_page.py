"""The LC-ranking page: panel detection, responsive layout, and the written pool bars.

Two layers:
  * unit — panel ordering, rank bands, the layout plan and the re-anchoring rule, on
    in-memory objects, so the logic is pinned independently of any .pptx;
  * integration — the real ``template/product_template.pptx`` valued from the seed DB and
    then filled, proving a panel populates end-to-end and that the template's hand-drawn
    quadrant bands, fake axis and dummy point labels do not survive it.

Deterministic: seed DB, no LLM.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pptx import Presentation

from studio.compute import compute_overall
from studio.template_fill import lc_page as L
from studio.template_fill.analyze import Shape, Slide, Template, analyze

PRODUCT_TEMPLATE = "template/product_template.pptx"
IN = 914400                                     # EMU per inch


def _scatter(shape_id: int, x: float, y: float) -> Shape:
    return Shape(shape_id=shape_id, name=f"Chart {shape_id}", kind="chart",
                 chart_type="XY_SCATTER (-4169)",
                 x=int(x * IN), y=int(y * IN), w=int(6.2 * IN), h=int(1.8 * IN))


def _page(*charts: Shape) -> Template:
    title = Shape(shape_id=1, name="Title 1", kind="text",
                  paragraphs=["Marsh Portfolio and LC ranking"])
    return Template(path="synthetic", width_emu=12192000, height_emu=6858000,
                    slides=[Slide(index=0, layout="", shapes=[title, *charts])])


def _grid() -> Template:
    return _page(_scatter(40, x=6.8, y=4.71), _scatter(10, x=0.4, y=2.34),
                 _scatter(30, x=0.4, y=4.71), _scatter(20, x=6.8, y=2.35))


# ── panel detection ──────────────────────────────────────────────────────────


def test_panels_are_ordered_top_row_first_then_left_to_right():
    # Authored out of order, and with the two panels of a row a hair apart vertically —
    # a plain (y, x) sort would read that as four rows of one.
    assert [p.shape_id for p in L.panels(_grid())] == [10, 20, 30, 40]


def test_only_the_ranking_page_is_a_panel():
    page = _page(_scatter(10, x=0.4, y=2.34))
    page.slides[0].shapes[0].paragraphs = ["Carrier vs Marsh growth rates"]
    assert L.panels(page) == []


# ── rank bands ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rank,band", [
    (1, L.LEAD), (2, L.LEAD),                   # the position to defend
    (3, L.STRONG), (5, L.STRONG),               # …still inside the deck's top-5 benchmark
    (6, L.CHASING), (8, L.CHASING),             # outside it, within reach
    (9, L.BEHIND), (30, L.BEHIND),              # the ground to make up
])
def test_band_of_follows_the_decks_top_five_benchmark(rank, band):
    assert L.band_of(rank) == band


# ── responsive layout ────────────────────────────────────────────────────────


def _frames():
    return [p.frame for p in L.panels(_grid())]


def test_one_country_takes_the_whole_page():
    [rect] = L.plan_layout(_frames(), 1)
    whole = L._union(_frames())
    assert (rect.x, rect.y, rect.w, rect.h) == (whole.x, whole.y, whole.w, whole.h)
    assert rect.h > _frames()[0].h * 2           # both rows, not a quarter of the page


def test_two_countries_share_the_page_side_by_side_at_full_height():
    frames = _frames()
    left, right = L.plan_layout(frames, 2)
    assert (left.x, left.w) == (frames[0].x, frames[0].w)      # the author's own columns
    assert (right.x, right.w) == (frames[1].x, frames[1].w)
    assert left.y == right.y and left.h == right.h == L._union(frames).h


@pytest.mark.parametrize("live", [3, 4])
def test_three_or_four_countries_keep_the_authored_grid(live):
    frames = _frames()
    assert L.plan_layout(frames, live) == frames[:live]


def test_a_layout_it_cannot_plan_falls_back_to_the_authored_grid():
    frames = _frames()
    assert L.plan_layout(frames, 0) == frames and L.plan_layout(frames, 9) == frames


# ── re-anchoring the panel's own furniture ───────────────────────────────────


def test_furniture_keeps_the_relationship_the_author_gave_it():
    from studio.template_fill.fill import _reanchor

    old = (0, 0, 600, 180)                       # a panel…
    new = (0, 0, 600, 400)                       # …grown to full height
    # A caption hugging the bottom edge stays under the panel.
    assert _reanchor((100, 190, 300, 20), old, new) == (100, 410, 300, 20)
    # A title above it stays above.
    assert _reanchor((10, -40, 300, 20), old, new) == (10, -40, 300, 20)
    # A rotated caption centred beside it stays centred.
    assert _reanchor((-60, 80, 120, 20), old, new) == (-60, 190, 120, 20)
    # A rule spanning the panel spans the new one.
    assert _reanchor((10, -10, 580, 4), old, new) == (10, -10, 580, 4)
    assert _reanchor((10, -10, 580, 4), old, (0, 0, 1200, 400)) == (10, -10, 1180, 4)


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


def test_every_panel_gets_a_payload_and_the_ones_in_scope_get_bars(product_template):
    panels = L.values(product_template, _result(["Singapore", "Japan"]))["lc_ranking"]
    assert len(panels) == len(L.panels(product_template)) == 4
    filled = [p for p in panels.values() if p["bars"]]
    assert len(filled) == 2 and all(p["country"] for p in filled)
    # The panels past the countries in scope carry no bars — the fill engine drops them
    # rather than shipping the template's authored example book under an erased title.
    assert [p["bars"] for p in panels.values() if not p["country"]] == [[], []]


def test_two_live_panels_are_re_laid_out_to_take_the_page_back(product_template):
    panels = list(L.values(product_template, _result(["Singapore", "Japan"]))["lc_ranking"].values())
    authored = L.panels(product_template)[0].frame
    live = [p["rect"] for p in panels if p["bars"]]
    assert len(live) == 2
    for rect in live:
        assert rect["h"] > authored.h * 1.9      # full height, not a quarter of the page


def test_bars_run_biggest_pool_first_and_carry_both_numbers(product_template):
    panel = next(p for p in L.values(product_template, _result(["Singapore"]))["lc_ranking"].values()
                 if p["bars"])
    sizes = [b["size"] for b in panel["bars"]]
    assert sizes == sorted(sizes, reverse=True) and len(sizes) > 1
    for bar in panel["bars"]:
        assert bar["size"] > 0 and bar["rank"] >= 1
        assert bar["band"] in {L.LEAD, L.STRONG, L.CHASING, L.BEHIND}
        assert bar["label"].startswith("$") and f"#{bar['rank']}" in bar["label"]


def test_a_product_subdeck_still_ranks_the_whole_line_of_business_mix(product_template):
    # The page is a PORTFOLIO view: a per-product sub-deck's own pin must not leave every
    # panel with the single bar of the product the sub-deck happens to be about.
    scoped = _result(["Singapore"], product="Property")
    panel = next(p for p in L.values(product_template, scoped)["lc_ranking"].values() if p["bars"])
    names = {b["name"] for b in panel["bars"]}
    assert len(names) > 1 and "Property" in names


# ── integration: the written panel ───────────────────────────────────────────


_BARS = [{"name": "Property", "size": 545e6, "rank": 6, "band": L.CHASING,
          "label": "$545M  ·  #6"},
         {"name": "Financial Lines", "size": 414e6, "rank": 3, "band": L.STRONG,
          "label": "$414M  ·  #3"},
         {"name": "Cyber", "size": 300e6, "rank": 1, "band": L.LEAD, "label": "$300M  ·  #1"}]


@pytest.fixture(scope="module")
def filled_page(tmp_path_factory):
    if not Path(PRODUCT_TEMPLATE).exists():
        pytest.skip("product template not present")
    from studio.template_fill.fill import fill_template

    panels = L.panels(analyze(PRODUCT_TEMPLATE))
    whole = L.plan_layout([p.frame for p in panels], 1)[0]
    payload = {f"{p.slide_idx}:{p.shape_id}": {"country": None, "bars": [],
                                               "rect": p.frame.to_dict()}
               for p in panels}
    payload[f"{panels[0].slide_idx}:{panels[0].shape_id}"] = {
        "country": "Singapore", "bars": _BARS, "rect": whole.to_dict()}
    doc = {"template_path": PRODUCT_TEMPLATE, "manifest": [],
           "values": {"lc_ranking": payload}, "overrides": {}, "map_overrides": {}, "added": {}}
    out = fill_template(doc, out_path=str(tmp_path_factory.mktemp("lc") / "lc.pptx"))
    return Presentation(out).slides[0], panels, whole


def _only_chart(slide):
    charts = [sh for sh in slide.shapes if getattr(sh, "has_chart", False)]
    assert len(charts) == 1, "the panels with no country must be removed whole"
    return charts[0]


def test_the_panel_is_rebuilt_as_a_bar_chart_at_its_planned_rect(filled_page):
    slide, _, whole = filled_page
    frame = _only_chart(slide)
    assert "BAR_CLUSTERED" in str(frame.chart.chart_type)
    assert (frame.left, frame.top, frame.width, frame.height) == (whole.x, whole.y,
                                                                  whole.w, whole.h)


def test_each_bar_is_coloured_by_the_carriers_rank_band(filled_page):
    from pptx.dml.color import RGBColor

    chart = _only_chart(filled_page[0]).chart
    plot = chart.plots[0]
    # PowerPoint plots the first category at the BOTTOM, so the biggest pool is written last.
    assert list(plot.categories) == [b["name"] for b in reversed(_BARS)]
    expected = {"lead": "6FBF56", "strong": "B0DC92", "chasing": "F0C3C2", "behind": "E6A09E"}
    for point, bar in zip(plot.series[0].points, reversed(_BARS)):
        assert point.format.fill.fore_color.rgb == RGBColor.from_string(expected[bar["band"]])
        assert point.data_label.text_frame.text == bar["label"]
    # The bars state both numbers themselves: no legend, no chart title, no value axis.
    assert not chart.has_legend and not chart.has_title
    assert not chart.value_axis.visible


def test_the_hand_drawn_quadrant_bands_and_fake_axis_do_not_survive(filled_page):
    slide, _, whole = filled_page
    inside = [sh for sh in slide.shapes
              if not getattr(sh, "has_chart", False) and sh.left is not None
              and whole.x <= sh.left + sh.width // 2 <= whole.x + whole.w
              and whole.y <= sh.top + sh.height // 2 <= whole.y + whole.h]
    # No painted band group, no dashed threshold line, no break mark…
    assert not [sh for sh in inside if sh.shape_type in (5, 6, 9)]
    # …no "$2,080M" tick faking a broken axis, and no "Product (1)" dummy label.
    texts = [sh.text_frame.text for sh in inside if getattr(sh, "has_text_frame", False)]
    assert not [t for t in texts if "Product" in t or "$" in t]


def test_the_size_caption_survives_and_moves_with_the_panel(filled_page):
    slide, panels, whole = filled_page
    caption = next(sh for sh in slide.shapes if getattr(sh, "has_text_frame", False)
                   and sh.text_frame.text.strip() == "Size of Marsh Portfolio")
    assert caption.top > panels[0].frame.y + panels[0].frame.h    # followed the panel down
    assert caption.top < whole.y + whole.h + IN                   # …and stayed under it
    # The rank caption goes: the bars put lines of business up the side, and each states
    # its own rank, so a rotated "Carrier Rank" would be labelling nothing.
    assert not [sh for sh in slide.shapes if getattr(sh, "has_text_frame", False)
                and "Rank" in sh.text_frame.text and sh.width < sh.height * 6]
