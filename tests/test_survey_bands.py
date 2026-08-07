"""The Carrier Survey table's cell banding — Δ vs prior year → the legend's colour.

Edges are the ones read off the template's own legend picture: the NEUTRAL band is
inclusive on both sides (|Δ| = 0.2 is white); every other edge lands in the MORE
extreme band (Δ = -0.5 is amber, Δ = +0.5 is mid-green, |Δ| = 1 is the extreme).
"""
from __future__ import annotations

import pytest

from studio.template_fill.survey import bands


@pytest.mark.parametrize("delta,expected", [
    (-3.0, "CF3638"),
    (-1.0, "CF3638"),          # edge: closes the red band
    (-0.99, "FFBF35"),
    (-0.5, "FFBF35"),          # edge: closes the amber band
    (-0.49, "FFF3DC"),
    (-0.21, "FFF3DC"),
    (-0.2, None),              # edge: neutral is inclusive
    (0.0, None),
    (0.2, None),               # edge: neutral is inclusive
    (0.21, "ABDC97"),
    (0.49, "ABDC97"),
    (0.5, "5BBF41"),           # edge: opens the mid-green band
    (0.99, "5BBF41"),
    (1.0, "008542"),           # edge: opens the dark-green band
    (4.0, "008542"),
])
def test_band_for_covers_every_edge(delta, expected):
    assert bands.band_for(delta) == expected


def test_band_for_none_delta_is_unfilled():
    assert bands.band_for(None) is None


def test_every_legend_colour_is_reachable():
    reached = {bands.band_for(d) for d in (-2, -0.7, -0.3, 0, 0.3, 0.7, 2)}
    assert reached == {"CF3638", "FFBF35", "FFF3DC", None, "ABDC97", "5BBF41", "008542"}
