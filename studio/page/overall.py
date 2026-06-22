"""Overall (QBR) page assembled from LIVE computed facts.

Calls the deterministic compute orchestrator, then renders KPIs, executive
commentary (rule-based), breakdown charts/tables, and whitespace. Drop-in for the
sample page — same renderers, real numbers.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from dash import html

from studio.compute import compute_overall
from studio.narrate import build_commentary
from studio.page import render

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
_ACCENTS = ["blue", "navy", "green", "teal"]


def _title(filters: Mapping[str, Any]) -> str:
    carrier = filters.get("carrier") or "Market"
    country = filters.get("country")
    return f"{carrier} — {country}" if country else str(carrier)


def build_overall_page(
    *,
    filters: Optional[Mapping[str, Any]] = None,
    breakdowns: Optional[List[str]] = None,
    flow: str = "gpr",
    engine: Any = None,
) -> html.Div:
    filters = filters or {}
    result = compute_overall(flow=flow, filters=filters, breakdowns=breakdowns, engine=engine)
    headline, points, actions = build_commentary(result, page="overall")

    year = filters.get("year")
    subtitle = (
        f"{('FY' + str(year)) if year else 'All years'} · Premium & market performance, "
        "broken down by your selected dimensions."
    )

    children: List[Any] = [
        render.page_header("QUARTERLY BUSINESS REVIEW", _title(filters), subtitle),
        render.kpi_strip(result.kpis),
        render.commentary(headline, points, actions=actions),
    ]

    # First breakdown → bar + SoW donut side by side.
    if result.breakdowns:
        first = result.breakdowns[0]
        top = sorted(first.rows, key=lambda r: r["premium"] or 0, reverse=True)[:10]
        sow_rows = [r for r in top if r.get("sow") is not None][:6]
        pair = [
            render.section(
                f"Premium by {first.label}",
                render.bar_chart([r["name"] for r in top], [r["premium"] for r in top]),
                eyebrow="BREAKDOWN",
                accent="blue",
            )
        ]
        if sow_rows:
            pair.append(
                render.section(
                    f"Share of Wallet by {first.label}",
                    render.donut([r["name"] for r in sow_rows], [r["sow"] for r in sow_rows]),
                    eyebrow="PENETRATION",
                    accent="teal",
                )
            )
        children.append(html.Div(pair, className="studio-grid-2"))

    # Every breakdown → a detail table.
    for i, section in enumerate(result.breakdowns):
        children.append(
            render.section(
                f"{section.label} Detail",
                render.fact_table(section.rows, _DETAIL_COLS, hidden=section.hidden),
                eyebrow="BREAKDOWN",
                accent=_ACCENTS[i % len(_ACCENTS)],
            )
        )

    # Whitespace.
    if result.whitespace:
        children.append(
            render.section(
                "Whitespace Opportunities",
                html.Div(
                    [
                        html.P(
                            "Industries where the market writes materially but you write nothing.",
                            className="studio-note",
                        ),
                        render.fact_table(result.whitespace, _WS_COLS),
                    ]
                ),
                eyebrow="GROW HERE",
                accent="amber",
            )
        )

    return html.Div(children)
