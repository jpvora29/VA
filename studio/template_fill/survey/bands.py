"""Δ-vs-prior-year → the Carrier Survey table's cell colour.

Pure and table-driven: the seven bands are read straight off the legend picture the
author placed on the slide (``template/survey_template.pptx``, shape 52), so the table
below IS the legend. Correcting a threshold is a one-line edit here and nowhere else.
"""
from __future__ import annotations

from typing import Optional, Tuple

RED = "CF3638"
AMBER = "FFBF35"
CREAM = "FFF3DC"
WHITE = "FFFFFF"                    # the legend's own neutral swatch — painted, not left bare
LIGHT_GREEN = "ABDC97"
GREEN = "5BBF41"
DARK_GREEN = "008542"

# (upper bound, closed at that bound?, colour), worst first. A delta takes the FIRST band
# it falls under; anything past the last row is the dark-green band. The neutral band is
# closed on BOTH sides — |Δ| = 0.2 reads as "no material change" — while every other edge
# belongs to the more extreme band, which is how the legend labels them
# ("=< to -1" is red, ">= to 1" is dark green). The neutral band is WHITE rather than
# unfilled: an unfilled cell shows whatever the table style bands underneath it, which
# reads as a colour the legend never gave — so "no material change" states itself.
_BANDS: Tuple[Tuple[float, bool, Optional[str]], ...] = (
    (-1.0, True, RED),
    (-0.5, True, AMBER),
    (-0.2, False, CREAM),
    (0.2, True, WHITE),
    (0.5, False, LIGHT_GREEN),
    (1.0, False, GREEN),
)


def band_for(delta: Optional[float]) -> Optional[str]:
    """The cell colour for a year-on-year score change (``None`` ⇒ leave unfilled).

    ``None`` in means the cell has no comparable prior-year score, which is not the same
    as "no change" — the number still prints, but nothing is claimed about its direction,
    so the cell keeps the template's own styling instead of taking the neutral white.
    """
    if delta is None:
        return None
    for upper, closed, colour in _BANDS:
        if delta < upper or (closed and delta == upper):
            return colour
    return DARK_GREEN
