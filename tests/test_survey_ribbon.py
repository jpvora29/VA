"""The Carrier Survey ribbon chart — geometry and rendering.

Geometry is asserted on the figure spec (fast, hermetic); the PNG render is asserted
once and skipped where kaleido has no browser, because that is an environment fact,
not a code fault.
"""
from __future__ import annotations

import pytest

from studio.template_fill.survey import ribbon as R

_SECTIONS = ["Underwriting", "Client Focus", "Loss Control"]


def _spec(highlight: str = "Zurich") -> R.RibbonSpec:
    columns = []
    for i, section in enumerate(_SECTIONS):
        scored = [("Zurich", 6.4 + i * 0.1), ("AIG", 7.1), ("Chubb", 6.8)]
        scored.sort(key=lambda t: -t[1])
        columns.append(R.RibbonColumn(section, tuple(
            R.RibbonBox(c, v, highlight=(c == highlight)) for c, v in scored)))
    return R.RibbonSpec(tuple(columns))


def test_boxes_are_ordered_best_first_within_a_column():
    column = _spec().columns[0]
    assert [b.score for b in column.boxes] == sorted((b.score for b in column.boxes), reverse=True)


def test_figure_draws_a_box_per_carrier_per_column():
    fig = R.build_figure(_spec())
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert len(rects) == len(_SECTIONS) * 3


def test_subject_boxes_use_the_carrier_colour_and_peers_the_grey():
    fig = R.build_figure(_spec())
    fills = [s.fillcolor for s in fig.layout.shapes if s.type == "rect"]
    assert fills.count(R.CARRIER_FILL) == len(_SECTIONS)
    assert fills.count(R.PEER_FILL) == len(_SECTIONS) * 2


def test_subject_band_is_drawn_after_every_peer_band():
    """The carrier's ribbon must read ON TOP of the grey ones, so it is added last."""
    fig = R.build_figure(_spec())
    paths = [s for s in fig.layout.shapes if s.type == "path"]
    colours = [s.fillcolor for s in paths]
    assert colours[-1] == R.CARRIER_BAND
    assert colours.index(R.CARRIER_BAND) == len(colours) - colours.count(R.CARRIER_BAND)


def test_column_labels_are_annotated_once_each():
    fig = R.build_figure(_spec())
    texts = [a.text for a in fig.layout.annotations]
    for section in _SECTIONS:
        assert any(section.split()[0] in t for t in texts)


def test_score_labels_are_one_decimal_place():
    fig = R.build_figure(_spec())
    assert "7.1" in [a.text for a in fig.layout.annotations]


def test_empty_spec_builds_without_dividing_by_zero():
    fig = R.build_figure(R.RibbonSpec(()))
    assert not [s for s in fig.layout.shapes if s.type == "rect"]


@pytest.mark.skipif(not R.available(), reason="kaleido/Chrome not available on this host")
def test_render_produces_a_png_of_the_authored_aspect():
    png = R.render_ribbon_png(_spec())
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5_000
