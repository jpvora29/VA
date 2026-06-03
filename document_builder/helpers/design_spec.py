"""Loader for the authoritative pitch-report design spec.

`document_builder/skills/pitch_report_design.md` is the single source of truth for
the report's palette, fonts, sizes, section order, and per-section accents. This
module parses that skill's YAML frontmatter into a `DesignSpec` and exposes typed
accessors. `config/report_config.py` sources its palette + fonts from here, so the
whole builder follows the skill.

Parsing failures NEVER break report generation: every value has a hardcoded
fallback equal to the historical constant, and `load_design_spec()` swallows
errors and returns the defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx.shared import Pt, RGBColor

try:
    import yaml
except ImportError:  # pragma: no cover - parsed via fallback below
    yaml = None

_SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "pitch_report_design.md"

# Fallbacks — identical to the historical report_config literals so a parse miss
# is visually a no-op.
_DEFAULT_PALETTE: Dict[str, str] = {
    "navy": "000F47",
    "electric_blue": "0B4BFF",
    "light_blue": "82BAFF",
    "white": "FFFFFF",
    "dark": "1E2832",
    "green_text": "2E7D32",
    "red_text": "C53532",
    "light_gray": "B9B6B1",
    "gray": "505F73",
    "green_fill": "E8F5E9",
    "red_fill": "FDECEA",
    "header_fill": "000F47",
    "zebra_fill": "F7F9FD",
    "kpi_fill": "EEF2F8",
    "kicker_blue": "7396CD",   # muted blue for kickers on the navy banner
    "subtitle_blue": "9BB9E6", # soft blue for banner subtitles
    "cover_bg": "F4F7FC",      # very light tint for cover accent panels
    "rule_soft": "D0D8E8",     # soft hairline rule under section titles
    "table_border": "D8DFF0",  # table cell hairline
}
_DEFAULT_FONTS: Dict[str, str] = {"heading": "Georgia Pro Light", "body": "Arial"}
_DEFAULT_SIZES: Dict[str, float] = {
    "heading": 28,
    "subheading": 18,
    "body": 10,
    "caption": 7,
    "section_title": 13,
    "kpi_value": 16,
    "kpi_label": 7,
    "table_header": 8.5,
    "table_body": 8.8,
    "cover_title": 40,
    "cover_subtitle": 20,
    "cover_kicker": 11,
    "cover_meta": 10,
    "page_header": 8,
    "page_footer": 8,
}
_DEFAULT_LABELS: Dict[str, str] = {
    "kicker": "MARSH ICG  —  CARRIER PERFORMANCE REPORT",
    "title": "Performance Analysis",
    "banner_title": "Performance Analysis Builder",
    "source": "Source — GPR, Carrier Survey",
    "confidentiality": "Marsh ICG  —  Strictly Private & Confidential",
}
_DEFAULT_SECTION_ORDER: List[str] = [
    "header_banner",
    "kpi_strip",
    "executive_narrative",
    "product_breakdown",
    "whitespace_analysis",
    "industry_analysis",
    "segment_analysis",
]
_DEFAULT_SECTION_ACCENTS: Dict[str, str] = {
    "whitespace_analysis": "red_text",
    "industry_analysis": "navy",
    "segment_analysis": "electric_blue",
}


@dataclass(frozen=True)
class DesignSpec:
    palette: Dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_PALETTE))
    fonts: Dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_FONTS))
    sizes: Dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_SIZES))
    section_order: List[str] = field(default_factory=lambda: list(_DEFAULT_SECTION_ORDER))
    section_accents: Dict[str, str] = field(
        default_factory=lambda: dict(_DEFAULT_SECTION_ACCENTS)
    )
    labels: Dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_LABELS))

    def label(self, key: str) -> str:
        return self.labels.get(key) or _DEFAULT_LABELS.get(key, "")

    def hex(self, key: str) -> str:
        """Return the bare 6-digit hex (no '#') for a palette key."""
        return (self.palette.get(key) or _DEFAULT_PALETTE.get(key, "000000")).lstrip("#")

    def hex_hash(self, key: str) -> str:
        """Return the '#RRGGBB' form for a palette key (for shading helpers)."""
        return "#" + self.hex(key)

    def rgb(self, key: str) -> RGBColor:
        return RGBColor.from_string(self.hex(key))

    def font(self, key: str) -> str:
        return self.fonts.get(key) or _DEFAULT_FONTS.get(key, "Arial")

    def pt(self, key: str) -> Pt:
        return Pt(float(self.sizes.get(key, _DEFAULT_SIZES.get(key, 10))))

    def accent_rgb(self, section: str) -> RGBColor:
        return self.rgb(self.section_accents.get(section, "navy"))


def _parse_frontmatter(text: str) -> Dict[str, Any]:
    if not text.startswith("---"):
        return {}
    try:
        _, fm, _ = text.split("---", 2)
    except ValueError:
        return {}
    if yaml is None:
        return {}
    return yaml.safe_load(fm) or {}


def _coerce_str_map(value: Any, default: Dict[str, str]) -> Dict[str, str]:
    if not isinstance(value, dict):
        return dict(default)
    merged = dict(default)
    merged.update({str(k): str(v) for k, v in value.items()})
    return merged


def _load() -> DesignSpec:
    try:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        meta = _parse_frontmatter(text)
    except Exception:  # noqa: BLE001 - never let styling break the report
        return DesignSpec()

    sizes = dict(_DEFAULT_SIZES)
    if isinstance(meta.get("sizes"), dict):
        for k, v in meta["sizes"].items():
            try:
                sizes[str(k)] = float(v)
            except (TypeError, ValueError):
                continue

    order = meta.get("section_order")
    section_order = (
        [str(s) for s in order] if isinstance(order, list) and order else list(_DEFAULT_SECTION_ORDER)
    )

    return DesignSpec(
        palette=_coerce_str_map(meta.get("palette"), _DEFAULT_PALETTE),
        fonts=_coerce_str_map(meta.get("fonts"), _DEFAULT_FONTS),
        sizes=sizes,
        section_order=section_order,
        section_accents=_coerce_str_map(
            meta.get("section_accents"), _DEFAULT_SECTION_ACCENTS
        ),
        labels=_coerce_str_map(meta.get("labels"), _DEFAULT_LABELS),
    )


_SPEC: Optional[DesignSpec] = None


def load_design_spec() -> DesignSpec:
    """Module-level singleton; parsed once per process."""
    global _SPEC
    if _SPEC is None:
        _SPEC = _load()
    return _SPEC
