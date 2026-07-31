"""The GWP-performance page: its TTM table, panel totals, title and CY-vs-PY bar charts.

Two layers:
  * unit — example-number rendering and page anatomy detection, on an in-memory template,
    so the rules are pinned independently of any .pptx;
  * integration — the real ``template/country_template.pptx`` filled from the seed DB,
    proving the page populates end-to-end and that the single-country rule holds.

Deterministic: seed DB, no LLM (``STUDIO_AI=off`` is not even needed — nothing here polishes).
"""
from __future__ import annotations

import pytest

from studio.compute import compute_overall
from studio.template_fill import gwp_page as G
from studio.template_fill.analyze import Shape, Slide, Template, analyze
from studio.template_fill.render import render_example
from studio.template_fill.sections import Section, section_of

COUNTRY_TEMPLATE = "template/country_template.pptx"


# ── render_example: a value in the style of the author's own example figure ───


@pytest.mark.parametrize("token,value,expected", [
    ("€106.5m", 105_400_000, "€105.4m"),          # currency symbol + scale + decimals kept
    ("-1.0%", -2.34, "-2.3%"),                    # percentage, sign from the data
    ("-1.0%", 9.87, "9.9%"),                      # a negative example may render positive
    ("+6.1%▲", 6.14, "+6.1%▲"),                   # forced sign kept, arrow follows the sign
    ("+6.1%▲", -6.14, "-6.1%▼"),                  # …and re-points when the data declines
    ("+0.3 pp\xa0", 1.26, "+1.3 pp\xa0"),         # a separated unit keeps its spacing
    ("+3", -2, "-2"),                             # bare integer
    ("$1,234M", 2_293_000_000, "$2,293M"),        # thousands grouping kept
    ("$xxx.xm", 5.0, "5.0"),                      # not an example figure → value as-is
])
def test_render_example_follows_the_authored_style(token, value, expected):
    assert render_example(token, value) == expected


def test_render_example_passes_through_non_numbers():
    assert render_example("€106.5m", None) == "€106.5m"
    assert render_example("€106.5m", "n/a") == "n/a"


# ── page anatomy, on an in-memory page ───────────────────────────────────────


def _text(shape_id: int, text: str, *, x: float = 0.0, y: float = 0.0,
          w: float = 1.0, h: float = 0.3, name: str = "Text Placeholder 2") -> Shape:
    emu = 914400
    return Shape(shape_id=shape_id, name=name, kind="text",
                 x=int(x * emu), y=int(y * emu), w=int(w * emu), h=int(h * emu),
                 paragraphs=[text])


def _gwp_page_slide() -> Slide:
    """A stripped-down copy of the authored page: title, waterfall panel, TTM table."""
    emu = 914400
    table = Shape(shape_id=11, name="Table 10", kind="table",
                  x=int(4 * emu), y=int(5.3 * emu), w=int(8 * emu), h=int(1.7 * emu),
                  table=[
                      ["Marsh GWP", "TTM April 2026", "TTM April 2025", "YoY Change"],
                      ["Marsh GWP", "$xxx.xxm", "$xxx.xxm", "+6.1%▲"],
                      ["QBE GWP Share %", "x.x%", "x.x%", "+0.3 pp"],
                      ["QBE GWP rank", "xx", "xx", "+3"],
                      ["Peer average GWP 1-5", "$xxx.xm", "$xxx.xm", "+10.7%▲"],
                      ["Peer average 1-5 GWP Share %", "x.x%", "x.x%", "+0.3 pp"],
                  ])
    return Slide(index=1, layout="3_Title Only", shapes=[
        _text(3, "Europe -1.0% GWP YoY growth", x=0.5, y=0.42, w=12.3, name="Title 2"),
        _text(19, "-1.0%", x=1.63, y=1.95, w=0.61),
        _text(81, "€106.5m", x=0.78, y=2.48, w=0.58),
        _text(82, "€105.4m", x=2.48, y=2.52, w=0.58),
        _text(77, "PY", x=0.97, y=6.47, w=0.20),
        _text(80, "CY", x=2.67, y=6.47, w=0.21),
        table,
    ])


def _template(slide: Slide) -> Template:
    return Template(path="<memory>", width_emu=12192000, height_emu=6858000, slides=[slide])


def test_page_is_classified_by_its_title():
    assert section_of(_gwp_page_slide()) is Section.GWP_PERFORMANCE


def test_page_anatomy_is_located_by_caption_and_geometry():
    page = G.pages(_template(_gwp_page_slide()))[0]
    assert page.title_id == 3
    # CY / PY totals are matched to their column labels, not to document order.
    assert page.panel.prior_id == 81 and page.panel.current_id == 82
    assert page.panel.yoy_id == 19
    table = page.table
    # The LATER period is the current column, whichever order the author listed them in.
    assert (table.shape_id, table.current_col, table.prior_col, table.change_col) == (11, 1, 2, 3)
    assert dict(table.rows) == {1: "marsh_gwp", 2: "sow", 3: "rank",
                                4: "peer_gwp", 5: "peer_sow"}


def test_reversed_period_columns_still_map_current_to_the_later_year():
    slide = _gwp_page_slide()
    table = next(sh for sh in slide.shapes if sh.kind == "table")
    table.table[0] = ["Marsh GWP", "TTM April 2025", "TTM April 2026", "YoY Change"]
    page = G.pages(_template(slide))[0]
    assert (page.table.current_col, page.table.prior_col) == (2, 1)


def test_augment_binds_every_page_slot():
    bindings = G.augment(_template(_gwp_page_slide()), [])
    roles = {b.role for b in bindings}
    assert "gwp:1:title" in roles
    assert {"gwp:1:panel:cy", "gwp:1:panel:py", "gwp:1:panel:yoy"} <= roles
    assert {"gwp:1:period:cy", "gwp:1:period:py"} <= roles      # the TTM column headers
    for metric in ("marsh_gwp", "sow", "rank", "peer_gwp", "peer_sow"):
        assert {f"gwp:1:{metric}:cy", f"gwp:1:{metric}:py", f"gwp:1:{metric}:chg"} <= roles
    assert all(b.placeholder is False for b in bindings)


def test_augment_is_idempotent():
    template = _template(_gwp_page_slide())
    once = G.augment(template, [])
    twice = G.augment(template, list(once))
    assert len(twice) == len(once)


def test_retitle_keeps_the_authored_wording():
    assert G._retitle("Europe -1.0% GWP YoY growth", "Singapore", 9.94) == \
        "Singapore 9.9% GWP YoY growth"
    assert G._retitle("no percentage here", "Singapore", 1.0) is None


# ── chart-axis classification ────────────────────────────────────────────────


def _bar(shape_id: int, categories) -> Shape:
    return Shape(shape_id=shape_id, name=f"Chart {shape_id}", kind="chart",
                 chart_type="BAR_CLUSTERED (57)", chart_categories=list(categories),
                 chart_series=[("CY", [1.0]), ("PY", [1.0])])


def test_charts_are_classified_by_their_authored_categories():
    slide = _gwp_page_slide()
    slide.shapes += [_bar(57, ["Property", "Marine", "Cyber"]),
                     _bar(63, ["Japan", "Singapore"])]
    vocab = {"Product_Line": ["Property", "Marine", "Cyber", "Casualty"],
             "Country": ["Japan", "Singapore", "Hong Kong"]}
    assert dict(G._classify_charts(slide, vocab)) == {57: "Product_Line", 63: "Country"}


def test_an_unmatched_chart_takes_the_remaining_dimension():
    # Authored example categories often match nothing real ("Germany" in an APAC book);
    # with one axis identified the other chart can only be the leftover dimension.
    slide = _gwp_page_slide()
    slide.shapes += [_bar(57, ["Property", "Marine", "Cyber"]),
                     _bar(63, ["Germany", "France", "Spain"])]
    vocab = {"Product_Line": ["Property", "Marine", "Cyber"],
             "Country": ["Japan", "Singapore"]}
    assert dict(G._classify_charts(slide, vocab)) == {57: "Product_Line", 63: "Country"}


# ── integration: the real template, filled from the seed DB ──────────────────


def _result(countries):
    return compute_overall(filters={"carrier": "Zurich", "country": countries, "year": 2025})


def _country_result(countries, country):
    """The per-country sub-deck's result, scoped exactly as ``assemble`` scopes it."""
    from dataclasses import replace

    from studio.template_fill.bindings import scope_to_country

    run = replace(_result(countries), scope_countries=tuple(countries))
    return scope_to_country(run, country)


@pytest.fixture(scope="module")
def country_template():
    return analyze(COUNTRY_TEMPLATE)


def test_real_page_values_populate_from_the_warehouse(country_template):
    values = G.values(country_template, _country_result(["Singapore", "Japan"], "Singapore"))
    page = G.pages(country_template)[0]
    s = page.slide_idx

    # No placeholder survives: every period cell carries a real number.
    for metric in ("marsh_gwp", "sow", "rank", "peer_gwp", "peer_sow"):
        assert isinstance(values[f"gwp:{s}:{metric}:cy"], (int, float))
        assert isinstance(values[f"gwp:{s}:{metric}:py"], (int, float))
        assert "x" not in str(values[f"gwp:{s}:{metric}:chg"])

    # The TTM headers name the ACTUAL periods, not the template's authored years.
    assert "2025" in values[f"gwp:{s}:period:cy"]
    assert "2024" in values[f"gwp:{s}:period:py"]

    # The title names the deck's own scope and its real growth.
    title = values[f"gwp:{s}:title"]
    assert title.startswith("Singapore ") and "GWP YoY growth" in title
    assert "Europe" not in title

    # Percentage-point rows stay in points, percentage rows keep their arrow.
    assert values[f"gwp:{s}:sow:chg"].strip().endswith("pp")
    assert values[f"gwp:{s}:marsh_gwp:chg"][-1] in "▲▼►"


def test_the_panel_and_title_report_the_CARRIER_gwp_not_the_marsh_book(country_template):
    """The page is captioned "GWP Performance YoY" on a carrier QBR, so its panel totals,
    its YoY box and its title are the CARRIER's book. Only the row the author labels
    "Marsh GWP" reports the whole Marsh book."""
    result = _country_result(["Singapore", "Japan"], "Singapore")
    values = G.values(country_template, result)
    s = G.pages(country_template)[0].slide_idx
    readings = G._readings(result, G._reporting_filters(result))
    carrier, marsh = readings["carrier_gwp"], readings["marsh_gwp"]

    # A carrier is a fraction of the book, so the two are genuinely different numbers.
    assert carrier.current < marsh.current
    assert carrier.change != marsh.change

    # The panel renders the carrier's totals, in the template's own €/millions style.
    assert values[f"gwp:{s}:panel:cy"] == render_example("€106.5m", carrier.current)
    assert values[f"gwp:{s}:panel:py"] == render_example("€106.5m", carrier.prior)
    assert values[f"gwp:{s}:panel:yoy"] == render_example("-1.0%", carrier.change)
    # …and the title quotes the same growth figure as the panel.
    assert values[f"gwp:{s}:panel:yoy"].lstrip("+") in values[f"gwp:{s}:title"]
    # The explicitly-labelled Marsh row still reports the whole book.
    assert values[f"gwp:{s}:marsh_gwp:cy"] == marsh.current


def test_bar_values_are_scaled_to_the_unit_the_caption_declares(country_template):
    # The page states its unit — "GWP Performance YoY (€M)" — so the bars are in millions.
    result = _country_result(["Singapore", "Japan"], "Singapore")
    values = G.values(country_template, result)
    readings = G._readings(result, G._reporting_filters(result))
    carrier = readings["carrier_gwp"]

    country = next(v for v in values["gwp_bars"].values()
                   if set(v["categories"]) <= {"Singapore", "Japan"})
    singapore = country["cy"][country["categories"].index("Singapore")]
    assert singapore == pytest.approx(carrier.current / 1e6, rel=1e-6)
    # Every bar is a sane millions figure, not raw currency.
    for series in values["gwp_bars"].values():
        assert all(0 < v < 100_000 for v in series["cy"] + series["py"] if v)


@pytest.mark.parametrize("caption,divisor", [
    ("GWP Performance YoY (€M)", 1e6),
    ("GWP Performance YoY ($B)", 1e9),
    ("GWP Performance YoY (K)", 1e3),
    ("GWP Performance YoY", 1e6),          # no unit stated → millions
])
def test_chart_scale_follows_the_pages_caption(caption, divisor):
    slide = _gwp_page_slide()
    slide.shapes.append(_text(133, caption, x=0.52, y=1.65, w=3.08, name="TextBox 132"))
    assert G._chart_divisor(slide) == divisor


def test_country_chart_is_filled_across_the_selected_countries(country_template):
    values = G.values(country_template, _country_result(["Singapore", "Japan"], "Singapore"))
    page = G.pages(country_template, vocab={"Product_Line": [], "Country": []})[0]
    bars = values["gwp_bars"]
    series = [v for v in bars.values() if set(v["categories"]) <= {"Singapore", "Japan"}]
    assert series, f"no country series among {list(bars)}"
    assert sorted(series[0]["categories"]) == ["Japan", "Singapore"]
    assert len(series[0]["cy"]) == len(series[0]["py"]) == 2
    assert page.slide_idx == int(next(iter(bars)).split(":")[0])


def test_single_country_run_does_not_plot_other_countries(country_template):
    # The rule: a country-vs-country comparison needs several countries. With one selected,
    # the chart carries only that country — never the template's authored example countries.
    values = G.values(country_template, _country_result(["Singapore"], "Singapore"))
    for series in values["gwp_bars"].values():
        assert "Germany" not in series["categories"]     # the authored example is gone
        countries = [c for c in series["categories"] if c in {"Japan", "Hong Kong", "Australia"}]
        assert not countries, f"unselected countries plotted: {countries}"


def test_product_chart_is_unaffected_by_the_country_rule(country_template):
    values = G.values(country_template, _country_result(["Singapore"], "Singapore"))
    product_series = [v for v in values["gwp_bars"].values()
                      if "Property" in v["categories"] or "Cyber" in v["categories"]]
    assert product_series, "the product breakdown chart must still fill"
    assert len(product_series[0]["categories"]) > 1
