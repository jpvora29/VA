"""Thumbnails of the TEMPLATE slides, for the Setup include/exclude panel.

An author deciding whether a page belongs in the deck should be able to see the page. The
renderer that answers that already exists — :mod:`studio.template_fill.preview_assets`
renders any ``.pptx`` to per-slide PNGs under ``assets/`` and caches them by file hash — so
this module is only about WHEN it runs, which is the part that matters on a form:

    :func:`urls`   never renders. It reads the cache and answers immediately, with ``None``
                   for anything not rendered yet, so painting the panel is free.
    :func:`warm`   renders the missing ones, once, on a background thread.

The two together mean the first paint of Setup is not held up by PowerPoint, and by the time
an author reaches the panel the thumbnails are there. A miss is not a failure: the row falls
back to its section icon, exactly as the canvas falls back to slide geometry.

These are the TEMPLATE's own slides — the author's example carrier, not the selection's. The
panel says so. A per-carrier thumbnail would have to be built from the run's data, which is
the deck itself, and the whole point of the panel is to choose before that is paid for.
"""
from __future__ import annotations

import threading
from typing import Dict, Iterable, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

#: Rendered wide enough to read a slide's layout in a popover, and NOT wider: the render
#: cache is keyed on the template file alone, so this shares whatever the canvas already
#: rendered for the same template rather than rendering a second copy of it.
WIDTH_PX = 1600

#: One warm per axis per process. The templates are fixed and the PNGs are cached on disk,
#: so a second pass would re-open PowerPoint to discover it has nothing to do.
_warmed: set = set()
_lock = threading.Lock()


def urls(axis: str) -> Tuple[Optional[str], ...]:
    """``(url or None, …)`` per slide of ``axis``'s template — cache read only.

    Renders nothing, so it is safe on the hot path of a Dash callback. Anything missing
    comes back ``None`` and is filled in by :func:`warm`.
    """
    from studio.template_fill.deck_slides import slide_count
    from studio.template_fill.preview_assets import _cached_backgrounds

    count = slide_count(axis)
    if not count:
        return ()
    try:
        path = _template_path(axis)
        return tuple(_cached_backgrounds(path, count)) if path else (None,) * count
    except Exception as exc:  # noqa: BLE001 — a missing thumbnail is not a failure
        logger.warning("slide_previews: cache read failed for %r (%s)", axis, exc)
        return (None,) * count


def urls_by_axis(axes: Iterable[str]) -> Dict[str, Tuple[Optional[str], ...]]:
    """:func:`urls` for several axes — what the Setup panel asks for in one go."""
    return {axis: urls(axis) for axis in axes}


def warm(axes: Sequence[str] = ()) -> None:
    """Render whatever is missing for ``axes`` (default: every registered axis).

    Synchronous and idempotent. Each axis is rendered at most once per process, and a
    template whose PNGs are already on disk costs a directory listing.
    """
    for axis in (axes or _registered()):
        with _lock:
            if axis in _warmed:
                continue
            _warmed.add(axis)
        _render(axis)


def warm_async(axes: Sequence[str] = ()) -> Optional[threading.Thread]:
    """:func:`warm` on a daemon thread — how app start-up asks for it.

    Start-up must not wait on PowerPoint (seconds per template, and it may not be installed
    at all), and nothing on the page depends on the answer: the panel paints without
    thumbnails and picks them up on its next repaint.
    """
    thread = threading.Thread(target=warm, args=(tuple(axes),),
                              name="studio-slide-previews", daemon=True)
    thread.start()
    return thread


def _render(axis: str) -> None:
    """One axis's missing slide PNGs, rendered in a single renderer session."""
    from studio.template_fill.deck_slides import slide_count
    from studio.template_fill.preview_assets import ensure_rendered_slide_backgrounds

    count = slide_count(axis)
    path = _template_path(axis)
    if not count or not path:
        return
    try:
        rendered = ensure_rendered_slide_backgrounds(path, count, width_px=WIDTH_PX)
        logger.info("slide_previews: %s — %d/%d slide thumbnail(s) ready",
                    axis, sum(1 for u in rendered if u), count)
    except Exception as exc:  # noqa: BLE001 — thumbnails are an aid, never a gate
        logger.warning("slide_previews: render failed for %r (%s)", axis, exc)


def _template_path(axis: str) -> str:
    from studio.template_fill.binding_map import template_path

    try:
        return template_path(axis)
    except Exception:  # noqa: BLE001 — an unregistered axis simply has no preview
        return ""


def _registered() -> Tuple[str, ...]:
    from studio.template_fill.binding_map import available
    from studio.template_fill.deck_slides import DECK_AXES

    names = set(available())
    return tuple(axis for axis in DECK_AXES if axis in names)
