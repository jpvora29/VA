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


# ── how the chart looks on the slide ─────────────────────────────────────────


def test_the_canvas_is_transparent():
    """The PNG is swapped into a picture frame on a tinted slide. Any canvas colour prints
    as a hard white panel around the chart."""
    fig = R.build_figure(_spec())
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert fig.layout.plot_bgcolor == "rgba(0,0,0,0)"


def test_the_subject_is_the_palettes_yellow():
    from studio.template_fill.survey import bands

    assert R.CARRIER_FILL == f"#{bands.YELLOW}"


def test_the_subjects_score_is_legible_on_yellow():
    """White on #FFBE00 fails at this size; the subject's own score is set dark."""
    fig = R.build_figure(_spec())
    scores = [a for a in fig.layout.annotations if a.text and a.text.strip("<b>/").replace(".", "").isdigit()]
    subject = [a for a in scores if a.font.color == R.CARRIER_SCORE_TEXT]
    peers = [a for a in scores if a.font.color == R.SCORE_TEXT]
    assert len(subject) == len(_SECTIONS) and peers
    assert R.CARRIER_SCORE_TEXT != R.SCORE_TEXT


def test_the_title_and_axis_labels_are_set_in_the_decks_navy():
    fig = R.build_figure(_spec())
    title = next(a for a in fig.layout.annotations if "Peers Ranked" in (a.text or ""))
    labels = [a for a in fig.layout.annotations if "Underwriting" in (a.text or "")]
    assert title.font.color == R.TITLE_TEXT and title.font.size == R.TITLE_PT
    assert labels and all(a.font.color == R.AXIS_TEXT for a in labels)
    assert all(a.font.size == R.AXIS_PT for a in labels)
    # Both are set bold — they sit under a table whose own labels are heavier than 11pt grey.
    assert title.text.startswith("<b>") and all(a.text.startswith("<b>") for a in labels)


def test_the_longest_authored_section_name_fits_two_lines():
    """Three lines ran off the bottom of the picture frame, clipping the last word."""
    longest = "Claims – Non-Claims Professionals"
    assert R._wrap(longest).count("<br>") == 1


def test_the_label_band_is_tall_enough_for_two_lines():
    """The labels hang below the plot floor; the floor has to leave them room."""
    assert R._PLOT_BOTTOM >= 0.28


def test_empty_spec_builds_without_dividing_by_zero():
    fig = R.build_figure(R.RibbonSpec(()))
    assert not [s for s in fig.layout.shapes if s.type == "rect"]


@pytest.mark.skipif(not R.available(), reason="kaleido/Chrome not available on this host")
def test_render_produces_a_png_of_the_authored_aspect():
    png = R.render_ribbon_png(_spec())
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5_000
