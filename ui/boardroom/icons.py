"""Curated Bootstrap-icon + tone pickers for the Boardroom editor.

The AI-generated widgets carry expressive icons (up-arrow, lightbulb, danger
shield…). When a user edits a widget by hand we want them to *pick* one of those
icons from a visual dropdown rather than type a raw ``bi bi-…`` class string. This
module is the single source of truth for that curated set plus the colour-coded
tone picker, so the editor never hard-codes icon classes.

``icon_options`` / ``tone_options`` return ``dcc.Dropdown`` option lists whose
``label`` is a Dash component (icon glyph + name). Component labels are supported by
the project's Dash build; if a future build rejects them, fall back to plain-text
labels here in one place.
"""
from __future__ import annotations

from typing import Dict, List

from dash import html

# ── Curated icon catalog: (class, human name), grouped for a tidy dropdown ──
ICON_GROUPS: List[tuple[str, List[tuple[str, str]]]] = [
    ("Trend", [
        ("bi bi-arrow-up-right", "Up / improving"),
        ("bi bi-arrow-down-right", "Down / declining"),
        ("bi bi-graph-up-arrow", "Growth"),
        ("bi bi-graph-down-arrow", "Decline"),
        ("bi bi-dash-lg", "Flat / no change"),
    ]),
    ("Money", [
        ("bi bi-currency-dollar", "Currency"),
        ("bi bi-cash-stack", "Premium / cash"),
        ("bi bi-piggy-bank", "Savings"),
        ("bi bi-percent", "Rate / share"),
    ]),
    ("Rank & performance", [
        ("bi bi-trophy", "Rank / winner"),
        ("bi bi-award", "Award"),
        ("bi bi-bar-chart-line", "Bar chart"),
        ("bi bi-pie-chart", "Mix / share"),
        ("bi bi-speedometer2", "Performance"),
    ]),
    ("Insight", [
        ("bi bi-lightbulb", "Insight"),
        ("bi bi-stars", "Highlight"),
        ("bi bi-binoculars", "Outlook"),
        ("bi bi-lightning-charge", "Driver"),
        ("bi bi-bullseye", "Target"),
    ]),
    ("Risk & status", [
        ("bi bi-exclamation-triangle", "Caution"),
        ("bi bi-shield-exclamation", "Risk"),
        ("bi bi-shield-check", "Protected"),
        ("bi bi-check-circle", "OK / done"),
        ("bi bi-x-circle", "Adverse"),
        ("bi bi-info-circle", "Note"),
    ]),
    ("People & market", [
        ("bi bi-people", "Peers / broker"),
        ("bi bi-building", "Carrier"),
        ("bi bi-globe-americas", "Geography"),
        ("bi bi-geo-alt", "Market"),
        ("bi bi-box-seam", "Product"),
        ("bi bi-grid-3x3-gap", "Segment / whitespace"),
        ("bi bi-clipboard-data", "Report"),
        ("bi bi-diagram-3", "Structure"),
    ]),
]

# Flat lookup of every catalogued class (used to validate / dedupe).
ICONS: Dict[str, str] = {cls: name for _, items in ICON_GROUPS for cls, name in items}


def icon_options() -> List[dict]:
    """Dropdown options for the icon picker — each label shows the glyph + name."""
    opts: List[dict] = []
    for _group, items in ICON_GROUPS:
        for cls, name in items:
            opts.append({
                "label": html.Span([html.I(className=cls + " bm-opt-ic"), name],
                                    className="bm-opt"),
                "value": cls,
                "search": name,
            })
    return opts


# ── Tone picker: the four governed sentiments, shown as colour swatches ──
TONE_META: List[tuple[str, str]] = [
    ("neutral", "Neutral"),
    ("good", "Good"),
    ("warn", "Caution"),
    ("danger", "Adverse"),
]


def tone_options() -> List[dict]:
    """Dropdown options for the tone picker — each label carries a colour dot."""
    return [
        {
            "label": html.Span([html.Span(className=f"bm-tone-dot {value}"), label],
                               className="bm-opt"),
            "value": value,
            "search": label,
        }
        for value, label in TONE_META
    ]
