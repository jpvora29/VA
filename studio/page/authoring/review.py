"""Review mode — the client-ready checklist, computed from the materialized deck.

Every check reflects user edits, reordering and hidden pages; none hard-codes a
pass. ``review_body`` renders the checks, the page-count stat cards and the
export card (Export is no longer its own mode — the summary and the download
button live here; the PowerPoint itself is produced by the same ``qs-export``
callback the top bar uses).
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

from dash import html

from studio.deck.model import DeckSpec
from studio.page import document as D

from studio.page.authoring.derive import _hidden_ids, deck_counts


def _overflow_slides(deck: DeckSpec) -> List[int]:
    """Heuristic export-overflow flag: content that likely won't fit a 16:9 slide.

    Honest heuristic (not a true PPT layout measurement): too many rail points, an
    over-long action title, or a long table all risk clipping on export."""
    bad = []
    for i, s in enumerate(deck.slides):
        if s.layout not in ("insight", "decision", "exec", "swot", "initiatives"):
            continue
        too_many_points = len(s.takeaways) > 5
        long_title = len(s.title or "") > 120
        long_table = any(b.kind == "table" and len(getattr(b, "rows", [])) > 14 for b in s.blocks)
        if too_many_points or long_title or long_table:
            bad.append(i + 1)
    return bad


def _unsupported_blocks(deck: DeckSpec) -> List[str]:
    """Block kinds present in the deck that the PPT exporter cannot render natively."""
    kinds = {b.kind for s in deck.slides for b in s.blocks}
    return sorted(kinds - D.EXPORT_SUPPORTED_BLOCKS)


def _checks(deck: DeckSpec, doc: Optional[Mapping[str, Any]]) -> List[Tuple[str, bool, str]]:
    """Client-ready checklist computed from the *materialized* deck — so it reflects
    user edits, reordering and hidden pages, and never hard-codes a pass."""
    slides = deck.slides
    content = [s for s in slides if s.layout in ("insight", "decision", "exec")]
    with_ev = [s for s in content if s.evidence]
    sourced = [s for s in content if s.sources or s.evidence]
    decisions = [s for s in content if s.recommendation]
    owned = [s for s in decisions if s.owner]
    titled = [s for s in content if len((s.title or "").strip()) > 25 and " " in (s.title or "")]
    has_cover = any(s.layout == "cover" for s in slides)
    has_agenda = any(s.layout == "agenda" for s in slides)
    has_method = any(s.layout == "methodology" for s in slides)
    overflow = _overflow_slides(deck)
    unsupported = _unsupported_blocks(deck)

    return [
        ("Cover and agenda present", has_cover and has_agenda,
         f"Cover: {'yes' if has_cover else 'no'} · Agenda: {'yes' if has_agenda else 'no'}"),
        ("All main-deck claims have evidence", bool(content) and len(with_ev) == len(content),
         f"{len(with_ev)}/{len(content)} content slides carry linked facts"),
        ("Every content slide cites a source", bool(content) and len(sourced) == len(content),
         f"{len(sourced)}/{len(content)} slides expose source/evidence lineage"),
        ("Decisions have owners", len(decisions) == 0 or len(owned) == len(decisions),
         f"{len(owned)}/{len(decisions)} recommendations name an owner"),
        ("Action titles read as takeaways", bool(content) and len(titled) == len(content),
         f"{len(titled)}/{len(content)} titles are full sentences (heuristic)"),
        ("No likely export overflow", not overflow,
         "No clipping risk detected" if not overflow else f"Slides at risk: {', '.join(map(str, overflow))} (heuristic)"),
        ("Methodology / limitations included", has_method,
         "Appendix documents method and data gaps" if has_method else "No methodology slide in the deck"),
        ("Browser ↔ PPT parity", not unsupported,
         "Export renders this exact document — edits, order and hidden pages included"
         if not unsupported else f"Unsupported widget(s) for native export: {', '.join(unsupported)}"),
    ]


def _export_card(deck: DeckSpec, doc: Optional[Mapping[str, Any]]) -> html.Div:
    """The export summary + download button (folded in from the old Export mode)."""
    hidden_n = len(_hidden_ids(doc))
    total = len(deck.slides)
    note = (
        f"{total - hidden_n} of {total} pages export"
        + (f" · {hidden_n} hidden page(s) excluded" if hidden_n else "")
    )
    return html.Div(
        [
            html.Div([html.I(className="bi bi-filetype-pptx"), "Export"], className="qs-panel-title"),
            html.P(
                "The PowerPoint is produced by materializing this exact document — your "
                "edits, page order and hidden-page choices included. Nothing is regenerated.",
                className="qs-exp-sub",
            ),
            html.Div(note, className="qs-exp-note"),
            html.Button(
                [html.I(className="bi bi-download"), "Download .pptx"],
                id={"type": "qs-export", "loc": "review"},
                className="qs-generate-btn",
            ),
        ],
        className="qs-review-card qs-export-card",
    )


def review_body(deck: DeckSpec, doc: Optional[Mapping[str, Any]]) -> html.Div:
    checks = _checks(deck, doc)
    passed = sum(1 for _, ok, _ in checks if ok)
    ready = passed == len(checks)
    rows = [
        html.Div(
            [
                html.I(className=f"bi {'bi-check-circle-fill' if ok else 'bi-exclamation-circle'} qs-chk-icon {'ok' if ok else 'warn'}"),
                html.Div(
                    [html.Div(label, className="qs-chk-label"), html.Div(detail, className="qs-chk-detail")],
                ),
            ],
            className="qs-chk-row" + ("" if ok else " warn"),
        )
        for label, ok, detail in checks
    ]
    counts = deck_counts(deck, doc)
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [html.I(className="bi bi-patch-check"), "Client-ready review"],
                                className="qs-panel-title",
                            ),
                            html.Div(
                                f"{passed} of {len(checks)} checks passing",
                                className="qs-review-score" + (" ok" if ready else ""),
                            ),
                        ],
                        className="qs-review-head",
                    ),
                    html.Div(rows, className="qs-chk-list"),
                    html.Button(
                        [html.I(className=f"bi {'bi-patch-check-fill' if ready else 'bi-lock'}"),
                         "Mark client-ready" if ready else "Resolve issues to continue"],
                        className="qs-review-cta" + (" ok" if ready else ""),
                        disabled=not ready,
                    ),
                ],
                className="qs-review-card",
            ),
            html.Div(
                [
                    _stat_card("Pages (export)", counts["total"] - counts["hidden"], "bi-collection", "blue"),
                    _stat_card("Approved", counts["approved"], "bi-check2-circle", "green"),
                    _stat_card("Needs review", counts["needs_review"], "bi-clock-history", "amber"),
                    _stat_card("Hidden", counts["hidden"], "bi-eye-slash", "navy"),
                ],
                className="qs-review-stats",
            ),
            _export_card(deck, doc),
        ],
        className="qs-review",
    )


def _stat_card(label: str, value: int, icon: str, accent: str) -> html.Div:
    return html.Div(
        [
            html.Div(html.I(className=f"bi {icon}"), className=f"qs-rstat-icon {accent}"),
            html.Div([html.Div(str(value), className="qs-rstat-num"), html.Div(label, className="qs-rstat-lbl")]),
        ],
        className="qs-rstat",
    )
