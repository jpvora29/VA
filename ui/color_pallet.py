from dataclasses import dataclass, field


@dataclass
class ColorPalette:
    blue: list[str] = field(
        default_factory=lambda: [
            "#009DE0",
            "#001538",
            "#001F52",
            "#002C77",
            "#0065AC",
            "#3BB8F0",
            "#76D3FF",
            "#9FE0FF",
            "#C7EDFF",
            "#F0FAFF",
        ]
    )
    teal: list[str] = field(
        default_factory=lambda: [
            "#0077A0",
            "#00202E",
            "#040404",
            "#004C6C",
            "#006286",
            "#4EA8C2",
            "#9CD9E4",
            "#B8E5ED",
            "#D4F1F6",
            "#F0FDFF",
        ]
    )
    turquoise: list[str] = field(
        default_factory=lambda: [
            "#00968F",
            "#002423",
            "#004140",
            "#005E5D",
            "#007A76",
            "#4CB9AF",
            "#98DBCE",
            "#B7E7DE",
            "#D6F3ED",
            "#F5FFFD",
        ]
    )
    green: list[str] = field(
        default_factory=lambda: [
            "#00AC41",
            "#0F2415",
            "#1B4127",
            "#275D38",
            "#14853D",
            "#57C67A",
            "#ADDFB3",
            "#C4EAC9",
            "#DCF4DF",
            "#F3FFF5",
        ]
    )
    yellow: list[str] = field(
        default_factory=lambda: [
            "#FFBE00",
            "#2E1C00",
            "#623D00",
            "#965D00",
            "#C98600",
            "#FFD240",
            "#FFE580",
            "#FFEDA5",
            "#FFF4CA",
            "#FFFCEF",
        ]
    )

    blue_gray: list[str] = field(
        default_factory=lambda: [
            "#8096B2",
            "#1B222F",
            "#35425B",
            "#4E6287",
            "#627798",
            "#A2B7CD",
            "#BED3E4",
            "#D1E0EC",
            "#E5EDF4",
            "#F8FAFC",
        ]
    )

    @property
    def get_colors() -> list[str]:
        colors = []
        for te, tu, g, y, bg, b in zip(
            ColorPalette.teal,
            ColorPalette.turquoise,
            ColorPalette.green,
            ColorPalette.yellow,
            ColorPalette.blue_gray,
            ColorPalette.blue,
        ):
            colors.extend([te, tu, g, y, bg, b])
