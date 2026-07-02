"""Deterministic derivations from the real deck — status, counts, provenance.

Pure functions the whole shell shares: which story-item state a slide is in, the
page-count summary, and whether a field carries a user override. No layout state.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from dash import html

from studio.deck.model import DeckSpec, SlideSpec
from studio.page import document as D

from studio.page.authoring.constants import _STATUS_LABEL


def slide_status(slide: SlideSpec) -> Tuple[str, str]:
    """Map a slide to one visible story-item state (no score, just content rules)."""
    layout = slide.layout
    if layout in ("cover", "divider", "agenda"):
        return "ready", _STATUS_LABEL["ready"]
    if layout == "methodology":
        return "appendix", _STATUS_LABEL["appendix"]
    if layout == "exec":
        return "approved", _STATUS_LABEL["approved"]
    if layout in ("insight", "decision", "swot", "initiatives"):
        has_ev = bool(slide.evidence)
        has_reco = bool(slide.recommendation)
        if layout in ("insight", "decision") and not has_ev:
            return "needs-evidence", _STATUS_LABEL["needs-evidence"]
        if has_reco and slide.owner:
            return "approved", _STATUS_LABEL["approved"]
        if has_reco:
            return "needs-review", _STATUS_LABEL["needs-review"]
        return "draft", _STATUS_LABEL["draft"]
    return "draft", _STATUS_LABEL["draft"]


def deck_counts(deck: DeckSpec, doc: Optional[Mapping[str, Any]] = None) -> Mapping[str, int]:
    """Page-count summary for the top bar / pages mode (blueprint §"Page Count")."""
    statuses = [slide_status(s)[0] for s in deck.slides]
    return {
        "total": len(deck.slides),
        "appendix": sum(1 for s in statuses if s == "appendix"),
        "needs_review": sum(1 for s in statuses if s in ("needs-review", "needs-evidence")),
        "approved": sum(1 for s in statuses if s in ("approved", "client-ready")),
        "hidden": len(_hidden_ids(doc)),
    }


def _edited(doc: Optional[Mapping[str, Any]], idx: int, field: str) -> bool:
    """Whether the field at position ``idx`` carries a user override.

    The *display* value already comes from the materialized slide (edits applied),
    so the view only needs the provenance flag here — blueprint §3 "Everything
    Editable, Evidence Preserved": the generated value still lives in the document.
    """
    if not doc:
        return False
    sid = D.sid_at(doc, idx)
    return bool(sid and D.is_edited(doc, sid, field))


def _prov_badge(edited: bool) -> html.Span:
    return html.Span(
        [html.I(className="bi bi-pencil-fill"), "User edited"]
        if edited
        else [html.I(className="bi bi-shield-check"), "Rules verified"],
        className="qs-prov-badge" + (" edited" if edited else ""),
    )


def _hidden_ids(doc: Optional[Mapping[str, Any]]) -> set:
    return set((doc or {}).get("hidden", []))


def _is_hidden(doc: Optional[Mapping[str, Any]], idx: int) -> bool:
    sid = D.sid_at(doc, idx) if doc else None
    return bool(sid and sid in _hidden_ids(doc))
