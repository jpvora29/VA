"""The delivered deck as a slideshow — which pages, in what order, and their pictures.

Every page is the PowerPoint render the canvas shows, with the author's committed edits
drawn in, so what is presented is what Export hands over. Building it is a short
pipeline: the visible pages in order, the renders already on disk, the pages nobody has
looked at yet rendered now, and the edited pages redrawn with their edits.

Best-effort like the canvas: a page that cannot be rendered is presented as its title,
never as a crash.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from logger import get_logger
from studio.page import template_preview as TP
from studio.template_fill import registry
from studio.template_fill import text_edits as TE
from studio.template_fill.edited_render import edited_slide_url

logger = get_logger(__name__)


@dataclass(frozen=True)
class ShowSlide:
    """One page of the show."""

    title: str
    image_url: Optional[str]
    # The page carries retyped words its picture does not show (the edited render failed).
    edits_not_shown: bool = False


@dataclass(frozen=True)
class Slideshow:
    slides: Tuple[ShowSlide, ...]
    start: int = 0


def build_slideshow(tdoc: Mapping[str, Any], start: int = 0) -> Slideshow:
    """The show for a filled template doc, opening on position ``start``."""
    template, _ = registry.derive_manifest(tdoc["template_path"])
    count = len(template.slides)
    order = TP.visible_order(tdoc, count)
    urls = TP.stored_slide_urls(tdoc, count)
    urls = render_missing_pages(tdoc, order, urls)
    urls, unshown = render_edited_pages(tdoc, order, urls)
    slides = tuple(
        ShowSlide(
            title=template.slides[i].title() or template.slides[i].layout,
            image_url=urls[i],
            edits_not_shown=i in unshown,
        )
        for i in order
    )
    return Slideshow(slides=slides, start=clamp_start(start, len(slides)))


def clamp_start(start: Any, total: int) -> int:
    """``start`` as a valid position in a show of ``total`` pages (0 when it is not)."""
    try:
        pos = int(start)
    except (TypeError, ValueError):
        return 0
    return pos if 0 <= pos < total else 0


def render_missing_pages(tdoc: Mapping[str, Any], order: Sequence[int],
                         urls: Sequence[Optional[str]]) -> List[Optional[str]]:
    """``urls`` with every shown page that has no render yet rendered now.

    Only an assembled deck: its file IS the deliverable, while a single filled template's
    file on disk is the unfilled template, whose render would present the wrong words.
    """
    out = list(urls)
    missing = [i for i in order if not out[i]]
    if not missing or not tdoc.get("assembled"):
        return out
    from studio.template_fill.preview_assets import ensure_rendered_slide_backgrounds

    try:
        fresh = ensure_rendered_slide_backgrounds(tdoc["template_path"], len(out), only=missing)
    except Exception as exc:  # noqa: BLE001 — a missing picture is never worth a crash
        logger.warning("slideshow: rendering %d page(s) failed: %s", len(missing), exc)
        return out
    return [out[i] or fresh[i] for i in range(len(out))]


def render_edited_pages(tdoc: Mapping[str, Any], order: Sequence[int],
                        urls: Sequence[Optional[str]]) -> Tuple[List[Optional[str]], set]:
    """``urls`` with each edited page swapped for its render WITH the edits.

    Also returns the pages whose edits could not be drawn, so the show can say so rather
    than present the old words as if they were the deck's.
    """
    out = list(urls)
    edits = TE.text_edits(tdoc)
    if not edits:
        return out, set()
    edited = {a.slide_idx for key in edits if (a := TE.parse_address(key))}
    unshown = set()
    for page in order:
        if page not in edited:
            continue
        url = (edited_slide_url(tdoc["template_path"], edits, page, len(out))
               if tdoc.get("assembled") else None)
        if url:
            out[page] = url
        else:
            unshown.add(page)
    return out, unshown
