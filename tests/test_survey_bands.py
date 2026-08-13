"""The Carrier Survey table's cell banding — Δ vs prior year → the legend's colour.

Edges are the ones read off the template's own legend picture: the NEUTRAL band is
inclusive on both sides (|Δ| = 0.2 is white); every other edge lands in the MORE
extreme band (Δ = -0.5 is yellow, Δ = +0.5 is mid-green, |Δ| = 1 is the extreme).

Two separate things are pinned here, on purpose. The THRESHOLDS are named by band, so
repainting the palette cannot break a test about where a band starts. The palette's own hex
values are pinned once, in :func:`test_the_palette_is_the_brands_own`, so a colour change is
a deliberate one-line edit against the brand's list rather than a diff scattered over
fifteen parametrised cases.
"""
from __future__ import annotations

import pytest

from studio.template_fill.survey import bands


@pytest.mark.parametrize("delta,expected", [
    (-3.0, bands.RED),
    (-1.0, bands.RED),                  # edge: closes the red band
    (-0.99, bands.YELLOW),
    (-0.5, bands.YELLOW),               # edge: closes the yellow band
    (-0.49, bands.LIGHT_YELLOW),
    (-0.21, bands.LIGHT_YELLOW),
    (-0.2, bands.WHITE),                # edge: neutral is inclusive
    (0.0, bands.WHITE),
    (0.2, bands.WHITE),                 # edge: neutral is inclusive
    (0.21, bands.LIGHT_GREEN),
    (0.49, bands.LIGHT_GREEN),
    (0.5, bands.GREEN),                 # edge: opens the mid-green band
    (0.99, bands.GREEN),
    (1.0, bands.DARK_GREEN),            # edge: opens the dark-green band
    (4.0, bands.DARK_GREEN),
])
def test_band_for_covers_every_edge(delta, expected):
    assert bands.band_for(delta) == expected


def test_band_for_none_delta_is_unfilled():
    """No comparable prior year is not "no change": the cell keeps the template's own
    styling rather than taking the neutral band's white."""
    assert bands.band_for(None) is None


def test_every_legend_colour_is_reachable():
    reached = {bands.band_for(d) for d in (-2, -0.7, -0.3, 0, 0.3, 0.7, 2)}
    assert reached == set(bands.LEGEND)


def test_the_palette_is_the_brands_own():
    """The one place the hex values are stated. The table IS the legend printed under it,
    so a swatch that drifts from the brand's list is a page that contradicts its own key."""
    assert (bands.RED, bands.YELLOW, bands.LIGHT_YELLOW,
            bands.LIGHT_GREEN, bands.GREEN, bands.DARK_GREEN) == (
        "C53532", "FFBE00", "FFF3DA", "B0DC92", "6ABF30", "14853D")
    # Neutral stays plain white — it is the legend's own "no material change" swatch.
    assert bands.WHITE == "FFFFFF"


def test_the_legend_lists_every_band_once():
    assert len(bands.LEGEND) == len(set(bands.LEGEND)) == 7
