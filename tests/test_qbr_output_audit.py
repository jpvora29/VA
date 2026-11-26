"""QBR deck output audit — the four reported defects and the leftovers found with them.

Driven by ``tests/qbr_awkward_book.py``: a book shaped like real data (twelve lines, a
carrier that leads small lines, ranks deep, writes no Marine and has no peer group), which
the tidy seed DB never exercised.

1. The LC ranking page dropped lines the carrier ranks top 5 in.
2. "Peer GWP" / "Peer SoW" printed the five-largest-carrier average with no peer set.
3. Product pages kept "Marine Feedback" for a carrier that writes no Marine.
4. The LC rank axis stretched to the deepest rank, cramming its tick labels.
5. Found by the audit: unresolved figures shipped the template's "$xxx.xm" / "x.x%"
   dummies, the overall band's SoW change rounded to "+0▲", "up 1 places".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import qbr_awkward_book as B

from studio import compute as C
from studio.template_fill import lc_page as L

# ── 1. every top-5 line is plotted ───────────────────────────────────────────


def _row(name: str, rank: int | None) -> dict:
    return {"name": name, "rank": rank}


def test_every_top_five_line_survives_the_point_cap():
    # Biggest carrier premium first, as product_breakdown_rows returns them.
    rows = [_row(f"Big {i}", 8 + i) for i in range(6)] + [
        _row("Small lead", 1),
        _row("Niche", 4),
    ]
    names = [r["name"] for r in L.select_lines(rows, cap=6)]
    assert "Small lead" in names and "Niche" in names
    assert len(names) == 6  # the cap still trims the lines OUTSIDE the top 5


def test_top_five_lines_are_never_cut_even_past_the_cap():
    rows = [_row(f"Lead {i}", 1 + i % 5) for i in range(8)] + [_row("Deep", 20)]
    names = [r["name"] for r in L.select_lines(rows, cap=6)]
    assert names == [f"Lead {i}" for i in range(8)]


def test_unranked_lines_are_not_plotted():
    assert L.select_lines([_row("No rank", None), _row("Ranked", 3)]) == [
        _row("Ranked", 3)
    ]


# ── 4. the rank axis keeps the author's scale ────────────────────────────────


@pytest.mark.parametrize(
    ("rank", "row", "label"),
    [
        (1, 1.0, "Cyber"),
        (10, 10.0, "Cyber"),
        (11, 10.5, "Cyber (#11)"),
        (37, 10.5, "Cyber (#37)"),
    ],
)
def test_a_deep_rank_sits_on_the_floor_row_and_names_its_rank(rank, row, label):
    point = L.RankPoint("Cyber", 1.0, rank, L.band_of(rank))
    assert (point.row, point.label) == (row, label)
    assert point.to_dict()["row"] == row


def test_the_exported_rank_axis_is_never_widened():
    from pptx import Presentation
    from pptx.chart.data import XyChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    from studio.template_fill.fill import _LC_RANK_AXIS_MAX, _fill_rank_scatter

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    data = XyChartData()
    data.add_series("x").add_data_point(1, 1)
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.XY_SCATTER, 0, 0, Inches(4), Inches(3), data
    ).chart
    deep = L.RankPoint("Environmental", 5e6, 37, L.band_of(37)).to_dict()
    top = L.RankPoint("Terrorism", 9e6, 1, L.band_of(1)).to_dict()
    _fill_rank_scatter(chart, [top, deep], "Singapore")

    assert chart.value_axis.maximum_scale == _LC_RANK_AXIS_MAX
    assert list(chart.plots[0].series[0].values) == [1.0, L.FLOOR_ROW]
    labels = [p.data_label.text_frame.text for p in chart.plots[0].series[0].points]
    assert labels == ["Terrorism", "Environmental (#37)"]


# ── 3. product names are rewritten in one pass ───────────────────────────────


def test_the_product_rewrite_is_one_pass():
    from studio.template_fill.fill import _product_rule

    rule = _product_rule(["Marine", "Energy", "Energy & Power"], "Energy & Power")
    assert rule.sub("Energy & Power", "Marine Feedback") == "Energy & Power Feedback"
    # Text that already names the deck's own product is left as it is.
    assert (
        rule.sub("Energy & Power", "Energy & Power Feedback")
        == "Energy & Power Feedback"
    )


def test_nothing_to_rewrite_gives_no_rule():
    from studio.template_fill.fill import _product_rule

    assert _product_rule(["Cyber"], "Cyber") is None


# ── 5. leftovers ─────────────────────────────────────────────────────────────


def test_an_unresolved_figure_ships_blank_not_the_dummy():
    from studio.template_fill.fill import _ships_blank

    assert _ships_blank({"role": "peer_gwp", "value_kind": "money", "token": "$xx.xM"})
    # The KPI band registers its cells as text; the token still gives the dummy away.
    assert _ships_blank({"role": "peer_gwp", "value_kind": "text", "token": "xxxM"})
    assert not _ships_blank({"role": None, "value_kind": "money", "token": "$xx.xM"})
    assert not _ships_blank({"role": "note:x", "value_kind": "text", "token": "……"})


@pytest.mark.parametrize(
    ("role", "token", "expected"),
    [
        ("sow_yoy", "PY (+x▲)", "PY (+x.x%▲)"),
        ("sow_yoy", "PY (+x.x%▲)", "PY (+x.x%▲)"),
        ("rank_yoy", "PY (+x▲)", "PY (+x▲)"),
    ],
)
def test_a_share_change_renders_as_a_percentage(role, token, expected):
    from studio.template_fill.kpi_band import share_token
    from studio.template_fill.render import render_token

    assert share_token(role, token) == expected
    if role == "sow_yoy":
        assert render_token(share_token(role, token), 0.4, "text") == "PY (+0.4%▲)"


@pytest.mark.parametrize("value", [0.03, -0.04])
def test_a_change_that_rounds_to_nothing_reads_flat(value):
    from studio.template_fill.render import render_example, render_token

    assert render_token("PY (+x.x%▲)", value, "pct") == "PY (0.0%►)"
    assert render_example("+10.7%▲", value) == "+0.0%►"


def test_a_one_place_rank_move_is_singular():
    from studio.template_fill.stance import _places

    assert (_places(1), _places(-1), _places(3)) == ("1 place", "1 place", "3 places")


# ── integration over the awkward book ────────────────────────────────────────


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    return B.build(tmp_path_factory.mktemp("awkward") / "book.sqlite")


def _run(engine, carrier=B.SUBJECT, *, peers=None, countries=B.COUNTRIES):
    from studio.compute import compute_overall

    return compute_overall(
        filters={"carrier": carrier, "country": list(countries), "year": 2025},
        engine=engine,
        peers=peers,
    )


def _scope(engine, carrier=B.SUBJECT):
    return {"Carrier_Group": carrier, "Country": ["Singapore"], "Year": 2025}


def test_no_peer_set_means_no_peer_benchmark(engine):
    filters = _scope(engine)
    assert C.peer_set_totals("gpr", filters, engine, B.SUBJECT) is None


def test_an_existing_peer_group_is_the_benchmark(engine):
    filters = _scope(engine, B.PEERED)
    peer = C.peer_set_totals("gpr", filters, engine, B.PEERED)
    assert peer is not None and peer["n_peers"] == 5
    # The five named peers average 40.0 … 30.8M in each big line (Singapore, unscaled).
    assert peer["current"] > 0 and peer["sow"] > 0


def test_custom_peers_are_the_benchmark_for_a_carrier_with_no_group(engine):
    filters = _scope(engine)
    pinned = ("AIG", "Allianz", "Chubb", "QBE", "Sompo")
    peer = C.peer_set_totals("gpr", filters, engine, B.SUBJECT, pinned)
    assert peer is not None and peer["n_peers"] == 5


def test_the_kpi_roles_stay_blank_without_a_peer_set(engine):
    from studio.template_fill.bindings import resolve_roles

    roles = resolve_roles(_run(engine))
    assert not {k for k in roles if k.startswith("peer_")}
    with_peers = resolve_roles(_run(engine, B.PEERED))
    assert {"peer_gwp", "peer_sow"} <= set(with_peers)


def test_the_template_product_word_is_rewritten_for_a_carrier_without_it(engine):
    from studio.template_fill.bindings import product_label_vocab, product_vocab

    run = _run(engine)
    assert "Marine Cargo" not in product_vocab(
        run
    )  # Subject Co writes no Marine at all
    assert "Marine" in product_label_vocab(
        run
    )  # …but the template's word is still rewritten


def test_the_lc_page_plots_the_small_lines_the_carrier_leads(engine):
    from dataclasses import replace

    from studio.template_fill.bindings import scope_to_country

    run = replace(
        _run(engine, countries=("Singapore",)), scope_countries=("Singapore",)
    )
    scoped = scope_to_country(run, "Singapore")
    points = L.rank_points(
        scoped, {**L._reporting_filters(scoped), "Country": "Singapore"}
    )
    ranks = {p.name: p.rank for p in points}
    assert ranks.get("Terrorism") == 1 and ranks.get("Political Risk") == 2


# ── end to end: the assembled deck ───────────────────────────────────────────

_DUMMY = re.compile(r"\$x|x\.x|\bx{2,3}[MBmb]?\b|\bxyz\b|Country\s*\(\d\)")


def _deck_text(path: str) -> list[tuple[int, str]]:
    from pptx import Presentation

    def texts(shape):
        if shape.shape_type == 6:
            for child in shape.shapes:
                yield from texts(child)
            return
        if shape.has_text_frame:
            yield shape.text_frame.text
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    yield cell.text

    return [
        (i, text)
        for i, slide in enumerate(Presentation(path).slides, 1)
        for shape in slide.shapes
        for text in texts(shape)
    ]


def _table_rows(path: str) -> list[list[str]]:
    from pptx import Presentation

    return [
        [cell.text for cell in row.cells]
        for slide in Presentation(path).slides
        for shape in slide.shapes
        if getattr(shape, "has_table", False) and shape.has_table
        for row in shape.table.rows
    ]


def _peer_rows(path: str) -> list[list[str]]:
    """The country GWP table's "Peer average …" rows, label first."""
    return [
        row
        for row in _table_rows(path)
        if row and row[0].strip().startswith("Peer average")
    ]


def _scatter_panels(path: str) -> list:
    from pptx import Presentation

    return [
        sh.chart
        for slide in Presentation(path).slides
        for sh in slide.shapes
        if getattr(sh, "has_chart", False) and "SCATTER" in str(sh.chart.chart_type)
    ]


@pytest.fixture(scope="module")
def subject_deck(engine, tmp_path_factory):
    from studio.template_fill.assemble import assemble_deck

    if not Path("template/overall_template.pptx").exists():
        pytest.skip("templates not present")
    out = tmp_path_factory.mktemp("subject_deck")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("COMMENTARY_MODE", "auto")  # no model client in tests: rules prose
        return assemble_deck(
            _run(engine), out_path=str(out / "deck.pptx"), work_dir=str(out / "work")
        )


@pytest.mark.e2e
def test_the_deck_ships_no_template_dummies(subject_deck):
    leftovers = [(i, t[:80]) for i, t in _deck_text(subject_deck) if _DUMMY.search(t)]
    assert leftovers == []


@pytest.mark.e2e
def test_product_pages_are_titled_for_their_own_product(subject_deck):
    titles = [t for _i, t in _deck_text(subject_deck) if t.strip().endswith("Feedback")]
    assert titles and not [t for t in titles if "Marine" in t]
    assert "Terrorism Feedback" in titles


@pytest.mark.e2e
def test_no_peer_figure_without_a_peer_set(subject_deck):
    rows = _peer_rows(subject_deck)
    assert rows  # the rows are there, labelled — and every figure in them is empty
    assert [row for row in rows if any(cell.strip() for cell in row[1:])] == []
    # Every peer callout carries its caption only: no amount, no share above it.
    callouts = [
        t for _i, t in _deck_text(subject_deck) if re.search(r"Peer\s+(GWP|SoW)$", t)
    ]
    assert callouts
    assert [c for c in callouts if re.search(r"\d", c.split("Peer")[0])] == []


@pytest.mark.e2e
def test_the_lc_panels_carry_the_top_five_lines_on_the_authored_scale(subject_deck):
    panels = _scatter_panels(subject_deck)
    assert panels
    for chart in panels:
        labels = [p.data_label.text_frame.text for p in chart.plots[0].series[0].points]
        assert {"Terrorism", "Political Risk"} <= set(labels)
        assert chart.value_axis.maximum_scale == 11.0


@pytest.mark.e2e
def test_a_carrier_with_a_peer_group_gets_its_peer_figures(
    engine, tmp_path, monkeypatch
):
    from studio.template_fill.assemble import assemble_deck

    if not Path("template/overall_template.pptx").exists():
        pytest.skip("templates not present")
    monkeypatch.setenv("COMMENTARY_MODE", "auto")
    deck = assemble_deck(
        _run(engine, B.PEERED, countries=("Singapore",)),
        out_path=str(tmp_path / "deck.pptx"),
        work_dir=str(tmp_path / "work"),
    )
    rows = _peer_rows(deck)
    gwp = next(row for row in rows if "Share" not in row[0])
    assert re.match(r"\$\d", gwp[1].strip()) and re.match(r"\$\d", gwp[2].strip())
    assert [(i, t[:80]) for i, t in _deck_text(deck) if _DUMMY.search(t)] == []
