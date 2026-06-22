"""Sample data + assembled QBR-style page — for visual development of the Studio UI.

Lets the page (and its styling) be rendered and screenshotted without a DB or
login. The shapes here mirror what the real cuts/fact-store will hand the
renderers, so the renderers built against this work unchanged on live data.
"""
from __future__ import annotations

from typing import Any, Dict, List

from dash import html

from studio.page import render
from studio.page.format import money

# Analyses checklist for the form rail, in the agreed nav order
# (Overall → Product → Country → Market → Rank → Peer).
CUT_GROUPS: List[Dict[str, Any]] = [
    {
        "label": "Overall",
        "cuts": [
            {"name": "overall_kpis", "label": "Headline KPIs", "default": True},
            {"name": "overall_commentary", "label": "Executive commentary", "default": True},
            {"name": "overall_trend", "label": "Premium trend (YoY)", "default": True},
        ],
    },
    {
        "label": "Product",
        "cuts": [
            {"name": "product_top_bottom", "label": "Top & bottom products", "default": True},
            {"name": "product_appetite", "label": "Appetite (share of portfolio)", "default": True},
            {"name": "product_sow", "label": "Share of wallet", "default": True},
            {"name": "product_whitespace", "label": "Whitespace", "default": True},
        ],
    },
    {
        "label": "Country",
        "note": "Per country: product · industry · market · rank",
        "cuts": [
            {"name": "country_breakdown", "label": "Per-country breakdown", "default": False},
            {"name": "country_swot", "label": "SWOT", "default": False},
        ],
    },
    {
        "label": "Market",
        "cuts": [
            {"name": "market_size", "label": "Market size & Marsh share", "default": False},
            {"name": "market_growth", "label": "Growth vs market", "default": False},
        ],
    },
    {
        "label": "Rank",
        "cuts": [{"name": "rank_similar", "label": "Vs similar-rank carriers", "default": False}],
    },
    {
        "label": "Peer",
        "cuts": [{"name": "peer_average", "label": "Peer average comparison", "default": False}],
    },
]

# ── sample breakdown rows ────────────────────────────────────────────────────
_PRODUCTS = [
    {"name": "Property", "premium": 52_300_000, "sow": 21.4, "yoy": 9.8},
    {"name": "Casualty", "premium": 41_100_000, "sow": 17.9, "yoy": 4.1},
    {"name": "Financial Lines", "premium": 28_700_000, "sow": 12.2, "yoy": 33.6},
    {"name": "Marine", "premium": 19_400_000, "sow": 15.1, "yoy": -6.2},
    {"name": "Cyber", "premium": 9_800_000, "sow": 6.8, "yoy": 58.4},
]
_INDUSTRIES = [
    {"name": "Manufacturing", "premium": 48_200_000, "sow": 18.4, "yoy": 12.1},
    {"name": "Financial Services", "premium": 39_750_000, "sow": 22.7, "yoy": 6.4},
    {"name": "Construction & Engineering", "premium": 28_100_000, "sow": 14.2, "yoy": -3.8},
    {"name": "Technology & Telecom", "premium": 21_900_000, "sow": 9.1, "yoy": 31.5},
    {"name": "Healthcare & Life Sciences", "premium": 17_400_000, "sow": 11.8, "yoy": 4.2},
    {"name": "Agriculture", "premium": 2_350_000, "sow": 3.1, "yoy": -1.2},
    {"name": "Hospitality & Leisure", "premium": 1_780_000, "sow": 2.4, "yoy": -8.9},
    {"name": "Public Administration", "premium": 1_240_000, "sow": 1.9, "yoy": 2.0},
    {"name": "Mining & Metals", "premium": 980_000, "sow": 1.2, "yoy": -14.3},
    {"name": "Education", "premium": 610_000, "sow": 0.8, "yoy": 5.5},
]
_BUSINESS_LINES = [
    {"name": "Commercial Property", "premium": 33_900_000, "sow": 19.2, "yoy": 7.4},
    {"name": "General Liability", "premium": 24_600_000, "sow": 16.1, "yoy": 2.8},
    {"name": "D&O", "premium": 16_200_000, "sow": 13.5, "yoy": 27.1},
    {"name": "Cargo", "premium": 11_300_000, "sow": 14.8, "yoy": -4.0},
]
_COVER_LINES = [
    {"name": "Fire & Perils", "premium": 21_400_000, "sow": 20.1, "yoy": 6.0},
    {"name": "Business Interruption", "premium": 14_900_000, "sow": 17.6, "yoy": 11.2},
    {"name": "Professional Indemnity", "premium": 9_700_000, "sow": 12.0, "yoy": 18.9},
    {"name": "Theft", "premium": 3_200_000, "sow": 8.4, "yoy": -2.1},
]
_WHITESPACE = [
    {"name": "Renewable Energy", "market": 31_500_000, "carrier": 0},
    {"name": "Pharmaceuticals", "market": 22_800_000, "carrier": 0},
    {"name": "Aviation & Aerospace", "market": 14_300_000, "carrier": 0},
]

_DETAIL_COLS = [
    {"key": "name", "label": "Segment", "align": "left"},
    {"key": "premium", "label": "GWP", "kind": "money", "align": "right"},
    {"key": "sow", "label": "Share of Wallet", "kind": "pct", "align": "right"},
    {"key": "yoy", "label": "YoY", "kind": "delta", "align": "right"},
]
_WS_COLS = [
    {"key": "name", "label": "Industry", "align": "left"},
    {"key": "market", "label": "Market GWP", "kind": "money", "align": "right"},
    {"key": "carrier", "label": "Your GWP", "kind": "money", "align": "right"},
]


def build_overall_demo() -> Any:
    kpis = [
        {"label": "Total GWP", "value": money(157_300_000), "delta": "+8.2% YoY", "tone": "good", "icon": "bi-cash-stack"},
        {"label": "Market Rank", "value": "#6 of 41", "delta": "▲ 2 places", "tone": "good", "icon": "bi-trophy"},
        {"label": "Share of Marsh Book", "value": "16.4%", "delta": "+1.1 pts", "tone": "good", "icon": "bi-pie-chart"},
        {"label": "Whitespace", "value": "3", "delta": "$68.6M opportunity", "tone": "warn", "icon": "bi-bullseye"},
    ]

    cmt = render.commentary(
        "Zurich grew premium +8.2% to USD 157.3M in Singapore, climbing two ranks to #6, "
        "led by Financial Lines and Cyber — but three material industries remain unwritten.",
        [
            {"label": "Momentum.", "text": "Cyber (+58.4%) and Financial Lines (+33.6%) drove growth; both clear the significance floor.", "tone": "good"},
            {"label": "Soft spots.", "text": "Marine (-6.2%) and Mining & Metals (-14.3%) declined against a flat-to-up market.", "tone": "danger"},
            {"label": "Penetration.", "text": "Share of wallet is strongest in Financial Services (22.7%) and weakest in Education (0.8%).", "tone": "neutral"},
            {"label": "Opportunity.", "text": "Renewable Energy, Pharmaceuticals and Aviation are written by the market (> $5M each) but not by Zurich — $68.6M of whitespace.", "tone": "warn"},
        ],
        actions=[
            "Defend Marine renewals; review pricing against the -6.2% slide.",
            "Build a Renewable Energy appetite statement — largest single whitespace ($31.5M).",
            "Scale the Cyber book while growth and rate environment are favourable.",
        ],
    )

    return html.Div(
        [
            render.page_header(
                "QUARTERLY BUSINESS REVIEW",
                "Zurich — Singapore",
                "FY2025 · Premium & market performance, broken down by product and industry.",
            ),
            render.kpi_strip(kpis),
            cmt,
            html.Div(
                [
                    render.section(
                        "Premium by Product Line",
                        render.bar_chart(
                            [r["name"] for r in _PRODUCTS], [r["premium"] for r in _PRODUCTS]
                        ),
                        eyebrow="BREAKDOWN",
                        accent="blue",
                    ),
                    render.section(
                        "Share of Wallet by Product",
                        render.donut(
                            [r["name"] for r in _PRODUCTS], [r["sow"] for r in _PRODUCTS]
                        ),
                        eyebrow="PENETRATION",
                        accent="teal",
                    ),
                ],
                className="studio-grid-2",
            ),
            render.section(
                "Industry Detail",
                render.fact_table(_INDUSTRIES, _DETAIL_COLS),
                eyebrow="BREAKDOWN · SIC MAJOR CLASS",
                accent="navy",
            ),
            html.Div(
                [
                    render.section(
                        "By Business Line",
                        render.fact_table(_BUSINESS_LINES, _DETAIL_COLS),
                        eyebrow="BREAKDOWN",
                        accent="green",
                    ),
                    render.section(
                        "By Cover Line",
                        render.fact_table(_COVER_LINES, _DETAIL_COLS),
                        eyebrow="BREAKDOWN",
                        accent="blue",
                    ),
                ],
                className="studio-grid-2",
            ),
            render.section(
                "Whitespace Opportunities",
                html.Div(
                    [
                        html.P(
                            "Industries where the market writes materially (> $5M) but you write nothing.",
                            className="studio-note",
                        ),
                        render.fact_table(_WHITESPACE, _WS_COLS),
                    ]
                ),
                eyebrow="GROW HERE",
                accent="amber",
            ),
        ]
    )
