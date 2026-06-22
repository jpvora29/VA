"""On-screen QBR slide renderer — consulting-grade 16:9 slides.

Every content slide follows the same frame: an **action title** at the top, a
**left commentary rail** (key takeaways) beside the **right-hand visual**
(chart / table / SWOT / initiative cards), and a footer with the logo, the
confidentiality line, and the page number. The same `SlideSpec` exports to .pptx.
"""
from __future__ import annotations

from typing import Any, List

from dash import html

from studio.deck.model import SlideSpec
from studio.page import render

_MAX_RAIL_POINTS = 4
_QUADRANTS = [
    ("strengths", "Strengths", "good", "bi-shield-check"),
    ("weaknesses", "Weaknesses", "danger", "bi-exclamation-triangle"),
    ("opportunities", "Opportunities", "blue", "bi-rocket-takeoff"),
    ("threats", "Threats", "warn", "bi-shield-exclamation"),
]


# ── shared pieces ────────────────────────────────────────────────────────────


def _rail(takeaways: List[dict], *, heading: str = "Key takeaways") -> html.Div:
    items = []
    for p in list(takeaways)[:_MAX_RAIL_POINTS]:
        tone = p.get("tone", "neutral")
        label = (p.get("label") or "").strip()
        items.append(
            html.Div(
                [
                    html.Span(className=f"studio-rail-dot {tone}"),
                    html.Div(
                        [
                            html.Span(label + " ", className="studio-rail-label") if label else None,
                            html.Span(p.get("text", ""), className="studio-rail-text"),
                        ]
                    ),
                ],
                className="studio-rail-item",
            )
        )
    return html.Div(
        [
            html.Div([html.I(className="bi bi-lightbulb"), heading], className="studio-rail-head"),
            html.Div(items, className="studio-rail-list"),
        ],
        className="studio-slide-rail",
    )


def _visual(block: Any) -> Any:
    kind = block.kind
    if kind == "chart":
        if block.chart == "donut":
            return render.donut(block.labels, block.values, height=250)
        return render.bar_chart(block.labels, block.values, height=250)
    if kind == "table":
        return render.fact_table(block.rows, block.columns, hidden=block.hidden)
    return None


def _kpi_band(items) -> html.Div:
    stats = []
    for k in items:
        tone = k.get("tone", "neutral")
        stats.append(
            html.Div(
                [
                    html.Div(str(k["label"]).upper(), className="studio-stat-label"),
                    html.Div(str(k["value"]), className="studio-stat-value"),
                    html.Div(k.get("delta") or "", className=f"studio-stat-delta {tone}"),
                ],
                className="studio-stat",
            )
        )
    return html.Div(stats, className="studio-stat-band")


def _swot(block) -> html.Div:
    cards = []
    for key, label, tone, icon in _QUADRANTS:
        bullets = getattr(block, key, []) or []
        cards.append(
            html.Div(
                [
                    html.Div(
                        [html.I(className=f"bi {icon}"), label],
                        className=f"studio-swot-head {tone}",
                    ),
                    html.Ul([html.Li(b) for b in bullets], className="studio-swot-list"),
                ],
                className=f"studio-swot-card {tone}",
            )
        )
    return html.Div(cards, className="studio-swot-grid")


def _cards(block) -> html.Div:
    out = []
    for c in block.cards:
        tone = c.get("tone", "neutral")
        out.append(
            html.Div(
                [
                    html.Span(c.get("tag", ""), className=f"studio-init-tag {tone}"),
                    html.Div(c.get("title", ""), className="studio-init-title"),
                    html.Div(c.get("body", ""), className="studio-init-body"),
                ],
                className=f"studio-init-card {tone}",
            )
        )
    return html.Div(out, className="studio-init-grid")


def _footer(idx: int, total: int) -> html.Div:
    return html.Div(
        [
            html.Div(
                [html.Span("M", className="studio-slide-logo"), html.Span("Marsh ICG")],
                className="studio-slide-foot-brand",
            ),
            html.Span("Strictly Private & Confidential  ·  Source: GPR, Carrier Survey", className="studio-slide-foot-conf"),
            html.Span(str(idx), className="studio-slide-foot-num"),
        ],
        className="studio-slide-footer",
    )


def _header(slide: SlideSpec) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Span(slide.eyebrow, className="studio-slide-eyebrow") if slide.eyebrow else None,
                    html.Span(slide.question, className="studio-slide-question") if slide.question else None,
                ],
                className="studio-slide-kicker",
            ),
            html.H2(slide.title, className="studio-slide-title"),
            html.Div(className=f"studio-slide-rule {slide.accent}"),
        ],
        className="studio-slide-header",
    )


def _evidence_chips(evidence) -> Any:
    if not evidence:
        return None
    chips = [
        html.Div(
            [html.Span(e["label"], className="studio-ev-label"), html.Span(e["value"], className="studio-ev-value"),
             html.Span(e.get("detail", ""), className="studio-ev-detail") if e.get("detail") else None],
            className="studio-ev-chip",
        )
        for e in list(evidence)[:4]
    ]
    return html.Div(chips, className="studio-ev-row")


def _reco_strip(slide: SlideSpec) -> Any:
    if not slide.recommendation:
        return None
    chips = []
    if slide.owner:
        chips.append(html.Span([html.I(className="bi bi-person"), slide.owner], className="studio-reco-chip"))
    if slide.due_date:
        chips.append(html.Span([html.I(className="bi bi-calendar3"), slide.due_date], className="studio-reco-chip"))
    if slide.confidence:
        chips.append(html.Span([html.I(className="bi bi-bar-chart"), f"{slide.confidence} confidence"], className=f"studio-reco-chip conf-{slide.confidence}"))
    return html.Div(
        [
            html.Div([html.I(className="bi bi-flag-fill"), html.Span("RECOMMENDATION", className="studio-reco-label"),
                      html.Span(slide.recommendation, className="studio-reco-text")], className="studio-reco-main"),
            html.Div(chips, className="studio-reco-chips"),
        ],
        className="studio-reco-strip",
    )


def _methodology(slide: SlideSpec) -> html.Div:
    gaps = list(slide.takeaways)
    half = (len(gaps) + 1) // 2
    cols = [gaps[:half], gaps[half:]]
    grid = html.Div(
        [
            html.Div(
                [
                    html.Div([html.Span(g.get("label", ""), className="studio-gap-label"), html.Span(g.get("text", ""), className="studio-gap-text")],
                             className="studio-gap-item")
                    for g in col
                ],
                className="studio-gap-col",
            )
            for col in cols
        ],
        className="studio-gap-grid",
    )
    sources = (slide.meta or {}).get("sources", []) or list(slide.sources)
    src = html.Div([html.Span("SOURCES", className="studio-col-head"), html.Span("  ·  ".join(sources), className="studio-src-line")], className="studio-src") if sources else None
    return html.Div([grid, src], className="studio-method-body")


# ── per-layout body ──────────────────────────────────────────────────────────


def _body(slide: SlideSpec) -> Any:
    layout = slide.layout

    if layout == "exec":
        kpis = next((b for b in slide.blocks if b.kind == "kpis"), None)
        cards = next((b for b in slide.blocks if b.kind == "cards"), None)
        lower = html.Div(
            [
                _rail(slide.takeaways, heading="What it means"),
                html.Div(
                    [
                        html.Div("PRIORITY ACTIONS", className="studio-col-head"),
                        html.Ul([html.Li(c["title"]) for c in (cards.cards if cards else [])], className="studio-action-list"),
                    ],
                    className="studio-exec-actions",
                ),
            ],
            className="studio-exec-lower",
        )
        return html.Div([_kpi_band(kpis.items) if kpis else None, lower], className="studio-exec-body")

    if layout == "swot":
        return _swot(slide.blocks[0])

    if layout == "initiatives":
        return _cards(slide.blocks[0])

    if layout == "methodology":
        return _methodology(slide)

    # insight / decision (the workhorse): left rail + right visual + reco strip
    visual = _visual(slide.blocks[0]) if slide.blocks else None
    grid = html.Div(
        [
            html.Div([_rail(slide.takeaways), _evidence_chips(slide.evidence)], className="studio-rail-wrap"),
            html.Div(visual, className="studio-slide-visual"),
        ],
        className="studio-insight-grid",
    )
    return html.Div([grid, _reco_strip(slide)], className="studio-insight-body")


def render_slide(slide: SlideSpec, idx: int, total: int) -> html.Section:
    if slide.layout == "cover":
        return html.Section(
            [
                html.Div(
                    [
                        html.Div(slide.eyebrow, className="studio-slide-eyebrow on-dark"),
                        html.H1(slide.title, className="studio-slide-hero-title"),
                        html.P(slide.subtitle, className="studio-slide-hero-sub"),
                        html.Div(className="studio-hero-rule"),
                    ],
                    className="studio-slide-hero-copy",
                ),
                _footer(idx, total),
            ],
            className="studio-slide layout-cover",
            **{"data-idx": idx},
        )

    return html.Section(
        [_header(slide), html.Div(_body(slide), className="studio-slide-body"), _footer(idx, total)],
        className=f"studio-slide layout-{slide.layout}",
        **{"data-idx": idx},
    )


def render_deck(deck) -> html.Div:
    total = len(deck.slides)
    slides = [render_slide(s, i + 1, total) for i, s in enumerate(deck.slides)]
    stage = html.Div(slides, className="studio-stage", id="studio-stage")

    thumbs = [
        html.Button(
            [html.Span(str(i + 1), className="studio-thumb-num"), html.Span(s.title or s.eyebrow, className="studio-thumb-label")],
            className="studio-thumb" + (" active" if i == 0 else ""),
            **{"data-go": i},
        )
        for i, s in enumerate(deck.slides)
    ]
    filmstrip = html.Div(thumbs, className="studio-filmstrip", id="studio-filmstrip")

    controls = html.Div(
        [
            html.Button(html.I(className="bi bi-chevron-left"), className="studio-nav-btn", id="studio-prev", **{"data-dir": -1}),
            html.Span([html.Span("1", id="studio-counter-now"), " / ", str(total)], className="studio-counter"),
            html.Button(html.I(className="bi bi-chevron-right"), className="studio-nav-btn", id="studio-next", **{"data-dir": 1}),
            html.Button([html.I(className="bi bi-filetype-pptx"), "Export PPTX"], className="studio-deck-export", id="studio-export-pptx"),
        ],
        className="studio-deck-controls",
    )
    return html.Div([controls, stage, filmstrip], className="studio-deck")
