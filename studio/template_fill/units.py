"""How a figure is SAID in carrier-facing prose.

One module because one rule kept being broken in fourteen places. Share-of-wallet movement
is measured in percentage points, and every composer wrote it as ``f"{x:.1f}pp"`` — so the
deck told a carrier's executive team that its share "rose 1.3pp", an abbreviation that is
not English, is not in the glossary the reader has, and is read by half the room as
"percent" (a different and wrong claim: 7.8% to 9.1% is 1.3 percentage points, not 1.3%).

The unit rules live in ``core/definitions/terms.yaml`` under ``percentage_point``; this is
the rendering that obeys them. Pure functions over numbers — no state, no formatting
policy beyond the words.
"""
from __future__ import annotations

from typing import Optional

# Below this, "a point of share" reads better than a decimal that implies precision the
# comparison does not have. 0.04pp is noise; saying "held share flat" is the honest line.
_FLAT_BELOW = 0.05


def points(value: Optional[float], *, decimals: int = 1) -> str:
    """A percentage-point movement, spelled out: ``1.3`` → ``"1.3 percentage points"``.

    Singular where it should be ("1.0 percentage point"), so the sentence reads aloud.
    """
    if value is None:
        return ""
    magnitude = abs(float(value))
    noun = "percentage point" if round(magnitude, decimals) == 1.0 else "percentage points"
    return f"{magnitude:.{decimals}f} {noun}"


def points_of_share(value: Optional[float], *, decimals: int = 1) -> str:
    """The shorter form for a sentence that has already said "share".

    ``1.3`` → ``"1.3 points of share"``. Same unit, fewer words — a partner writing about
    share does not repeat "percentage" in every clause.
    """
    if value is None:
        return ""
    magnitude = abs(float(value))
    noun = "point of share" if round(magnitude, decimals) == 1.0 else "points of share"
    return f"{magnitude:.{decimals}f} {noun}"


def is_flat(value: Optional[float]) -> bool:
    """True when a share movement is too small to be worth a decimal."""
    return value is None or abs(float(value)) < _FLAT_BELOW
