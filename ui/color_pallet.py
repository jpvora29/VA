"""Brand colour palette for charts.

Marsh-style brand hues plus the derived ramps the chart engine
(`ui.chart_functions`) needs: a categorical series order, a single-hue
sequential ramp (pie/donut), and a small semantic set (waterfall up/down/total,
positive/negative deltas).

The previous `get_colors` was a broken `@property` (no `self`, no `return`, and
it read instance-only dataclass fields off the class), so charts silently fell
back to default Plotly colours. This rewrite exposes plain class-level lists and
helper methods so `ColorPalette.get_colors()` returns a real, de-duplicated list.
"""
from __future__ import annotations

from typing import List


class ColorPalette:
    """Class-level brand palette. All members are plain lists/strings so they can
    be read straight off the class (no instantiation required)."""

    # Each hue runs from its lead (brand) tone through dark anchors to light tints.
    blue: List[str] = [
        "#009DE0", "#001538", "#001F52", "#002C77", "#0065AC",
        "#3BB8F0", "#76D3FF", "#9FE0FF", "#C7EDFF", "#F0FAFF",
    ]
    teal: List[str] = [
        "#0077A0", "#00202E", "#004C6C", "#006286", "#4EA8C2",
        "#9CD9E4", "#B8E5ED", "#D4F1F6", "#F0FDFF", "#E6F6FA",
    ]
    turquoise: List[str] = [
        "#00968F", "#002423", "#004140", "#005E5D", "#007A76",
        "#4CB9AF", "#98DBCE", "#B7E7DE", "#D6F3ED", "#F5FFFD",
    ]
    green: List[str] = [
        "#00AC41", "#0F2415", "#1B4127", "#275D38", "#14853D",
        "#57C67A", "#ADDFB3", "#C4EAC9", "#DCF4DF", "#F3FFF5",
    ]
    yellow: List[str] = [
        "#FFBE00", "#2E1C00", "#623D00", "#965D00", "#C98600",
        "#FFD240", "#FFE580", "#FFEDA5", "#FFF4CA", "#FFFCEF",
    ]
    blue_gray: List[str] = [
        "#8096B2", "#1B222F", "#35425B", "#4E6287", "#627798",
        "#A2B7CD", "#BED3E4", "#D1E0EC", "#E5EDF4", "#F8FAFC",
    ]

    # Semantic colours (waterfall / signed deltas).
    positive: str = "#00AC41"   # increases, growth
    negative: str = "#E5484D"   # decreases, churn
    total: str = "#001F52"      # subtotal / total bars (brand navy)
    neutral: str = "#8096B2"

    # ── Categorical series order ──────────────────────────────────────────────
    @classmethod
    def get_colors(cls) -> List[str]:
        """Ordered, de-duplicated categorical palette for chart series.

        Interleaves the lead tone of each hue first (so the first handful of
        series are maximally distinct brand colours), then the secondary tones,
        and so on across the ramps.
        """
        hues = [cls.blue, cls.turquoise, cls.green, cls.yellow, cls.teal, cls.blue_gray]
        ordered: List[str] = []
        for tone_idx in range(max(len(h) for h in hues)):
            for hue in hues:
                if tone_idx < len(hue):
                    ordered.append(hue[tone_idx])
        # De-duplicate, preserving order.
        seen: set[str] = set()
        unique: List[str] = []
        for c in ordered:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    @classmethod
    def color_for(cls, index: int) -> str:
        """Series colour by position (cycles)."""
        palette = cls.get_colors()
        return palette[index % len(palette)]

    @classmethod
    def sequential(cls, n: int) -> List[str]:
        """A single-hue light→dark ramp of `n` colours (for pie / donut slices)."""
        if n <= 0:
            return []
        # Hand-tuned blue ramp from light to brand-dark, sampled to length n.
        ramp = [
            "#9FE0FF", "#76D3FF", "#3BB8F0", "#009DE0",
            "#0065AC", "#002C77", "#001F52", "#001538",
        ]
        if n >= len(ramp):
            # Cycle through the categorical palette for very high slice counts.
            return [cls.color_for(i) for i in range(n)]
        # Evenly sample the ramp so a small n still spans light→dark.
        step = (len(ramp) - 1) / max(n - 1, 1)
        return [ramp[round(i * step)] for i in range(n)]
