"""The headline KPI band — recognised by its header words, wherever the author puts it.

The curated binding maps pin cells by shape id, so moving the band onto another page (or
adding a column to it) silently unbinds every cell and the page ships ``xx.xB``. These tests
pin the content-based recognition that replaces that, and the one table it must NOT claim:
the per-product breakdown grid, whose headers overlap it.

Deterministic: in-memory templates plus the real ``template/*.pptx``. No DB, no LLM.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from studio.template_fill import kpi_band
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Slide, Template, analyze


def _table(rows, shape_id: int = 6) -> Slide:
    return Slide(index=0, layout="", shapes=[
        Shape(shape_id=shape_id, name="Table 5", kind="table", table=rows)])


_BAND = [
    ["Marsh GWP 2025", "Carrier GWP 2025", "SoW% 2025", "2025 Rank"],
    ["xx.xB", "x.xB", "x.x%", "x"],
    ["PY (-x.x%▼)", "PY (+x.x%▲)", "PY (+x▲)", "PY (+x▲)"],
]


def _roles_at(cells, row: int):
    return [role for _, where, role in cells if where[1] == row]


def test_the_value_row_and_the_prior_year_row_get_different_roles():
    cells = kpi_band.detect(_table(_BAND))
    assert _roles_at(cells, 1) == [R.ROLE_MARSH_GWP, R.ROLE_CARRIER_GWP,
                                   R.ROLE_SOW_PCT, R.ROLE_RANK]
    assert _roles_at(cells, 2) == [R.ROLE_MARSH_GWP_YOY, R.ROLE_CARRIER_GWP_YOY,
                                   R.ROLE_SOW_YOY, R.ROLE_RANK_YOY]


def test_a_peer_column_is_the_benchmark_not_the_carriers_own_premium():
    rows = [["Marsh GWP 2025", "Carrier GWP 2025", "Peer GWP 2025", "SoW% 2025", "2025 Rank"],
            ["x.xB", "xxxM", "xxxM", "x.x%", "x"],
            ["PY (-x.x%▼)", "PY (+x.x%▲)", "PY (+x.x%▲)", "PY (+x.x%▲)", "PY (+x▲)"]]
    assert _roles_at(kpi_band.detect(_table(rows)), 1) == [
        R.ROLE_MARSH_GWP, R.ROLE_CARRIER_GWP, R.ROLE_PEER_GWP, R.ROLE_SOW_PCT, R.ROLE_RANK]


def test_a_reordered_or_renamed_year_still_binds():
    rows = [["2024 Rank", "SoW% 2024", "Carrier GWP 2024", "Marsh GWP 2024"],
            ["x", "x.x%", "x.xB", "xx.xB"]]
    assert _roles_at(kpi_band.detect(_table(rows)), 1) == [
        R.ROLE_RANK, R.ROLE_SOW_PCT, R.ROLE_CARRIER_GWP, R.ROLE_MARSH_GWP]


def test_the_breakdown_grid_is_not_a_kpi_band():
    # It shares three header words (SoW, Rank, Peer GWP) but reports one row per product —
    # claiming it would rebind every row to the same carrier total.
    rows = [["Product", "GWP", "Var %", "SoW", "Rank", "Rank change", "Peer GWP"],
            ["Marine", "$xx.xm", "+x.x%", "x.x%", "x", "+x↑", "$xx.xm"]]
    assert kpi_band.detect(_table(rows)) == []


def test_a_table_without_both_headline_measures_is_not_a_band():
    rows = [["Carrier GWP 2025", "SoW% 2025", "2025 Rank"], ["x.xB", "x.x%", "x"]]
    assert kpi_band.detect(_table(rows)) == []


# ── against the real templates ───────────────────────────────────────────────


@pytest.mark.parametrize("name,slides", [("overall", [5]), ("product", [0, 1, 2, 3]),
                                         ("country", []), ("end", [])])
def test_the_shipped_templates_bind_their_bands_and_nothing_else(name, slides):
    path = f"template/{name}_template.pptx"
    if not Path(path).exists():
        pytest.skip(f"{name} template not present")
    template = analyze(path)
    assert [s.index for s in template.slides if kpi_band.detect(s)] == slides


def test_augment_binds_a_band_the_curated_map_never_knew_about():
    template = Template(path="synthetic", width_emu=1, height_emu=1, slides=[_table(_BAND)])
    bound = kpi_band.augment(template, [])
    assert {b.role for b in bound} == {
        R.ROLE_MARSH_GWP, R.ROLE_CARRIER_GWP, R.ROLE_SOW_PCT, R.ROLE_RANK,
        R.ROLE_MARSH_GWP_YOY, R.ROLE_CARRIER_GWP_YOY, R.ROLE_SOW_YOY, R.ROLE_RANK_YOY}
    assert not [b for b in bound if b.placeholder]
    # The template's own text becomes the token, so each value renders in the authored shape.
    assert {b.slot.token for b in bound} >= {"xx.xB", "x.xB", "x.x%", "x"}
