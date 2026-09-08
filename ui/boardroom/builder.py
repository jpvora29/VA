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

Nothing is manufactured to fill a step, and nothing empty is laid out to explain
itself: a widget with no content is dropped, and a page left with no widgets is
dropped with it. A board therefore only ever shows the steps this data can
actually answer — a page of "not available in this data" panels is a page the
reader has to work past for nothing.

Explainable widgets take precedence over the score-based ones they replaced, so
a digest carrying a watchlist does not also print the legacy severity bars, and
quarterly performance supersedes the annual timeline.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from ui.boardroom import model
from ui.boardroom.catalog import LIBRARY_BY_KIND

# The funnel: (page title, icon, the question it answers).
OVERVIEW = ("Overview", "bi bi-clipboard2-pulse", "How is the book doing?")
PAIN_POINTS = ("Pain points", "bi bi-exclamation-diamond", "Where is it losing ground, and against whom?")
PRODUCT = ("Product deep dive", "bi bi-boxes", "Which lines carry the book, and where is the headroom?")
INDUSTRY = ("Industry focus", "bi bi-buildings", "Inside the priority line, which industries to go after?")
BATTLECARDS = ("Battlecards", "bi bi-clipboard-data", "How do the carriers compare head to head?")


# The key that carries a widget's content, per digest section. A section whose
# key is empty has nothing to show, whatever note came with it. A section mapped
# to None (or not listed) is a plain list — being non-empty IS its content.
_CONTENT_KEY: Dict[str, Optional[str]] = {
    "kpis": None,
    "insights": None,
    "watchlist": "items",
    "headroom": "rows",
    "whitespace": "rows",
    "quarterly": "rows",
    "portfolio_map": "bubbles",
    "top_carriers": "carriers",
    "comparison": "subjects",
    "opportunity_map": "cells",
    "positioning": "points",
    "positioning_actual": "points",
    "battlecards": None,
    "opportunities": None,
    "timeline": None,
}


def section_has_content(digest: Dict[str, Any], name: str) -> bool:
    """True when a digest section carries something worth a panel."""
    section = (digest or {}).get(name)
    if not section:
        return False
    key = _CONTENT_KEY.get(name)
    if key is None:
        return True
    return bool(isinstance(section, dict) and section.get(key))


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
        self._placed: set[str] = set()

    # ── steps ──

    def add_overview(self) -> "BoardroomDocumentBuilder":
        """The headline numbers, the written read, and the trend behind them."""
        widgets = [
            self._section("kpis", kind="kpi"),
            self._section("insights"),
            self._commentary(),
            # Quarterly performance supersedes the annual timeline when the data
            # carries comparable quarters.
            self._section("quarterly") or self._timeline(),
        ]
        return self._add_page(OVERVIEW, widgets)

    def add_pain_points(self) -> "BoardroomDocumentBuilder":
        """What needs attention, and how the field is moving around it."""
        widgets = [
            self._section("watchlist"),
            self._section("top_carriers"),
            self._section("comparison"),
        ]
        return self._add_page(PAIN_POINTS, widgets)

    def add_product_deep_dive(self) -> "BoardroomDocumentBuilder":
        """Where the book sits against where it wins, and the money left over."""
        widgets = [
            # One positioning view, in preference order — the bubble map first,
            # the retired plots only for a saved board that still carries one.
            self._section("portfolio_map")
            or self._section("positioning_actual", size="lg")
            or self._section("positioning", size="lg"),
            self._section("headroom"),
        ]
        widgets.extend(self._charts())
        return self._add_page(PRODUCT, widgets)

    def add_industry_focus(self) -> "BoardroomDocumentBuilder":
        """The narrowest step: which industries to go after inside a product line."""
        widgets = [
            self._section("whitespace"),
            self._section("opportunities", kind="opportunity_radar", size="lg"),
            self._section("opportunity_map"),
        ]
        return self._add_page(INDUSTRY, widgets)

    def add_battlecards(self) -> "BoardroomDocumentBuilder":
        """The head-to-head cards, when the turn compared named carriers."""
        return self._add_page(BATTLECARDS, [self._section("battlecards")])

    def build(self) -> Dict[str, Any]:
        # A board with no supported step still has to render as a card, so it
        # keeps one empty Overview page rather than no page at all. (This used to
        # pass the icon positionally, where `widgets` goes — the page then held a
        # string and the renderer iterated its characters.)
        title, icon, caption = OVERVIEW
        pages = self._pages or [model.make_page(title, [], icon=icon, caption=caption)]
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

    def _commentary(self):
        """The written read. The watchlist IS the risk presentation now, so the
        legacy severity bars ride along only when nothing replaced them."""
        digest = self._digest
        risks = [] if section_has_content(digest, "watchlist") else (digest.get("risks") or [])
        if not (digest.get("headline") or digest.get("commentary") or risks):
            return None
        return self._widget(
            "commentary",
            {
                "headline": digest.get("headline", ""),
                "sections": digest.get("commentary", []),
                "risks": risks,
            },
            size="full",
        )

    def _timeline(self):
        """The annual timeline — a list, not a keyed section, so it has its own test."""
        if "timeline" in self._placed or not self._digest.get("timeline"):
            return None
        return self._widget("timeline", {"timeline": self._digest["timeline"]}, size="full")

    def _charts(self) -> List[Dict[str, Any]]:
        return [
            self._widget("charts", {"spec_index": i}, size="lg", title=f"Chart {i + 1}")
            for i in range(self._n_charts)
        ]

    def _widget(self, kind: str, data: Dict[str, Any], *, size: str = "md", title: str = ""):
        self._placed.add(kind)
        return model.make_widget(kind, data, origin="generated", size=size, title=title)

    def _section(self, name: str, *, size: str = "full", kind: str = ""):
        """The widget for one digest section, or ``None`` when it has no place.

        Two reasons it has none: the section is empty, or this kind is already on
        the board. Both checks live here so no ``add_*`` can forget one — the
        same panel appearing on two steps of the funnel reads as a bug, and it
        was one.
        """
        kind = kind or name
        if kind in self._placed or not section_has_content(self._digest, name):
            return None
        return self._widget(kind, {name: self._digest[name]}, size=size)

    def _add_page(self, spec, widgets: List[Any]) -> "BoardroomDocumentBuilder":
        """Add the step, unless every widget on it came back empty."""
        title, icon, caption = spec
        kept = [w for w in widgets if w is not None]
        if kept:
            self._pages.append(model.make_page(title, kept, icon=icon, caption=caption))
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
