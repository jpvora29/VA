"""Build an editable document from an AI `BoardroomDigest`, and add library widgets.

The digest's sections become *generated* widgets (origin='generated', with an
immutable evidence snapshot). Empty sections are skipped. Charts are referenced
by spec index so the live plotly figures (rebuilt each render from the message's
chart specs) can be slotted in.

**The board is a funnel.** Pages are laid out as the conversation a QBR actually
follows, each answering one question:

    1 Overview        How is the book doing?
    2 Pain points     Where is it losing ground, and against whom?
    3 Product         Which lines carry the book, and where is the headroom?
    4 Industry focus  Inside the priority line, which industries to go after?

Nothing is manufactured to fill a step: a page with no supported widget is
dropped, and a widget the data cannot support says so in its own empty state.
Explainable widgets take precedence over the score-based ones they replaced, so
a digest carrying a watchlist does not also print the legacy severity bars, and
quarterly performance supersedes the annual timeline.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List

from ui.boardroom import model
from ui.boardroom.catalog import LIBRARY_BY_KIND

# The funnel: (page title, icon, the question it answers).
OVERVIEW = ("Overview", "bi bi-clipboard2-pulse", "How is the book doing?")
PAIN_POINTS = ("Pain points", "bi bi-exclamation-diamond", "Where is it losing ground, and against whom?")
PRODUCT = ("Product deep dive", "bi bi-boxes", "Which lines carry the book, and where is the headroom?")
INDUSTRY = ("Industry focus", "bi bi-buildings", "Inside the priority line, which industries to go after?")
BATTLECARDS = ("Battlecards", "bi bi-clipboard-data", "How do the carriers compare head to head?")


class BoardroomDocumentBuilder:
    """Assembles the funnel one page at a time.

    Each ``add_*`` owns a whole step of the funnel, including deciding that the
    step is not supported by this digest (it then adds nothing and returns
    ``self``). ``build`` returns the document and does nothing else.
    """

    def __init__(self, digest: Dict[str, Any], n_charts: int = 0) -> None:
        self._digest = digest or {}
        self._n_charts = n_charts
        self._pages: List[Dict[str, Any]] = []

    # ── steps ──

    def add_overview(self) -> "BoardroomDocumentBuilder":
        """The headline numbers, the written read, and the trend behind them."""
        digest = self._digest
        widgets: List[Dict[str, Any]] = []
        if digest.get("kpis"):
            widgets.append(self._widget("kpi", {"kpis": digest["kpis"]}, size="full"))
        if digest.get("insights"):
            widgets.append(self._widget("insights", {"insights": digest["insights"]}, size="full"))
        # The watchlist IS the risk presentation now; the legacy severity bars
        # ride along in the commentary only when nothing replaced them.
        risks = [] if digest.get("watchlist") else (digest.get("risks") or [])
        if digest.get("headline") or digest.get("commentary") or risks:
            widgets.append(
                self._widget(
                    "commentary",
                    {
                        "headline": digest.get("headline", ""),
                        "sections": digest.get("commentary", []),
                        "risks": risks,
                    },
                    size="full",
                )
            )
        if digest.get("quarterly"):
            widgets.append(self._widget("quarterly", {"quarterly": digest["quarterly"]}, size="full"))
        elif digest.get("timeline"):
            widgets.append(self._widget("timeline", {"timeline": digest["timeline"]}, size="full"))
        return self._add_page(OVERVIEW, widgets)

    def add_pain_points(self) -> "BoardroomDocumentBuilder":
        """What needs attention, and how the field is moving around it."""
        digest = self._digest
        widgets: List[Dict[str, Any]] = []
        if digest.get("watchlist"):
            widgets.append(self._widget("watchlist", {"watchlist": digest["watchlist"]}, size="full"))
        if digest.get("top_carriers"):
            widgets.append(self._widget("top_carriers", {"top_carriers": digest["top_carriers"]}, size="full"))
        if digest.get("comparison"):
            widgets.append(self._widget("comparison", {"comparison": digest["comparison"]}, size="full"))
        return self._add_page(PAIN_POINTS, widgets)

    def add_product_deep_dive(self) -> "BoardroomDocumentBuilder":
        """Where the book sits against where it wins, and the money left over."""
        digest = self._digest
        widgets: List[Dict[str, Any]] = []
        if digest.get("portfolio_map"):
            widgets.append(self._widget("portfolio_map", {"portfolio_map": digest["portfolio_map"]}, size="full"))
        elif digest.get("positioning_actual"):
            widgets.append(
                self._widget("positioning_actual", {"positioning_actual": digest["positioning_actual"]}, size="lg")
            )
        elif digest.get("positioning"):
            widgets.append(self._widget("positioning", {"positioning": digest["positioning"]}, size="lg"))
        if digest.get("headroom"):
            widgets.append(self._widget("headroom", {"headroom": digest["headroom"]}, size="full"))
        for i in range(self._n_charts):
            widgets.append(self._widget("charts", {"spec_index": i}, size="lg", title=f"Chart {i + 1}"))
        return self._add_page(PRODUCT, widgets)

    def add_industry_focus(self) -> "BoardroomDocumentBuilder":
        """The narrowest step: which industries to go after inside a product line."""
        digest = self._digest
        widgets: List[Dict[str, Any]] = []
        if digest.get("whitespace"):
            widgets.append(self._widget("whitespace", {"whitespace": digest["whitespace"]}, size="full"))
        if digest.get("opportunities"):
            widgets.append(self._widget("opportunity_radar", {"opportunities": digest["opportunities"]}, size="lg"))
        if digest.get("opportunity_map"):
            widgets.append(self._widget("opportunity_map", {"opportunity_map": digest["opportunity_map"]}, size="full"))
        return self._add_page(INDUSTRY, widgets)

    def add_battlecards(self) -> "BoardroomDocumentBuilder":
        digest = self._digest
        widgets: List[Dict[str, Any]] = []
        if digest.get("battlecards"):
            widgets.append(self._widget("battlecards", {"battlecards": digest["battlecards"]}, size="full"))
        return self._add_page(BATTLECARDS, widgets)

    def build(self) -> Dict[str, Any]:
        pages = self._pages or [model.make_page(*OVERVIEW[:2])]
        document = model.make_document(
            title=self._digest.get("title", "Boardroom"),
            subtitle=self._digest.get("subtitle", ""),
            pages=pages,
            # The scope the answer was built from travels with the document, so
            # the board header, the exported slide and the composer agree.
            scope=list(self._digest.get("scope") or []),
        )
        return document

    # ── helpers ──

    def _widget(self, kind: str, data: Dict[str, Any], *, size: str = "md", title: str = ""):
        return model.make_widget(kind, data, origin="generated", size=size, title=title)

    def _add_page(self, spec, widgets: List[Dict[str, Any]]) -> "BoardroomDocumentBuilder":
        title, icon, caption = spec
        if widgets:
            self._pages.append(model.make_page(title, widgets, icon=icon, caption=caption))
        return self


def build_document_from_digest(digest: Dict[str, Any], n_charts: int = 0) -> Dict[str, Any]:
    """Lay a digest out as the funnel. Same signature the callers already use."""
    return (
        BoardroomDocumentBuilder(digest, n_charts)
        .add_overview()
        .add_pain_points()
        .add_product_deep_dive()
        .add_industry_focus()
        .add_battlecards()
        .build()
    )


def blank_page(doc: Dict[str, Any], *, template: str | None = None) -> str:
    """Add a blank (or template) page; return its id."""
    def _w(kind, size="md"):
        return model.make_widget(
            kind, copy.deepcopy(LIBRARY_BY_KIND[kind]["default_data"]), origin="user",
            size=size, title=LIBRARY_BY_KIND[kind]["label"],
        )

    widgets: List[Dict[str, Any]] = []
    title = "New page"
    if template == "exec_summary":
        title = "Executive summary"
        widgets = [_w("key_message", "full"), _w("commentary", "full")]
    elif template == "actions":
        title = "Actions & owners"
        widgets = [_w("action_tracker", "full")]
    page = model.make_page(title, widgets, icon="bi bi-file-earmark-plus", template=template)
    doc.setdefault("pages", []).append(page)
    return page["id"]


def add_library_widget(doc: Dict[str, Any], page_id: str, kind: str) -> str | None:
    """Append a user-library widget to a page; return its id."""
    spec = LIBRARY_BY_KIND.get(kind)
    page = model.find_page(doc, page_id)
    if not spec or not page:
        return None
    widget = model.make_widget(
        kind,
        copy.deepcopy(spec["default_data"]),
        origin="user",
        size=spec.get("size", "md"),
        title=spec["label"],
    )
    page["widgets"].append(widget)
    return widget["id"]
