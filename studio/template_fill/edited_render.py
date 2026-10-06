"""The edited slide, drawn by PowerPoint itself — what the canvas shows after Apply.

Retyped words used to be drawn in HTML over the render of the UNedited slide. However
carefully the browser copies size, weight and colour, it is not PowerPoint's text engine:
strokes looked heavier than the render's, a bold run's look spread over a whole line, and
"any change to text changes its formatting slightly" was the honest description.

So once an edit is committed, the slide is rendered again from a copy of the deck that
carries the edits — written by the same :func:`studio.template_fill.fill.apply_text_overrides`
the export uses, so the canvas shows exactly what the .pptx will say. One slide costs about
a second and a half of PowerPoint, which is why this happens on Apply and never per
keystroke (typing keeps its live HTML preview). Renders are cached per slide AND per its
edits, so returning to a page, or undoing back to an earlier wording, costs nothing.

Best-effort throughout: without a renderer the canvas keeps drawing the edits itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from logger import get_logger
from studio.template_fill import ppt_renderer
from studio.template_fill import preview_assets as PA
from studio.template_fill import text_edits as TE

logger = get_logger(__name__)

EDITED_DIR = "edited"
_WIDTH_PX = 1600          # the width every other slide render uses


def slide_edits(edits: Mapping[str, Any], slide_idx: int) -> Dict[str, Any]:
    """The edits that land on page ``slide_idx`` — the only ones its pixels depend on."""
    return {key: lines for key, lines in edits.items()
            if (address := TE.parse_address(key)) and address.slide_idx == slide_idx}


def _render_dir(pptx_path: str, slide_idx: int, edits: Mapping[str, Any]) -> Path:
    payload = json.dumps({"slide": slide_idx, "edits": edits}, sort_keys=True, default=str)
    key = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return PA.template_cache_dir(pptx_path) / EDITED_DIR / key


def _png(render_dir: Path, slide_idx: int) -> Path:
    return render_dir / f"slide-{slide_idx:03d}.png"


def edited_slide_url(pptx_path: str, edits: Mapping[str, Any], slide_idx: int,
                     slide_count: int, *, render: bool = True) -> Optional[str]:
    """The URL of page ``slide_idx`` rendered WITH its edits, or ``None``.

    ``render=False`` only looks in the cache (the filmstrip asks that way: a thumbnail is
    not worth a PowerPoint launch). ``None`` when the page has no edits, when no renderer
    is available, or when the render failed — the caller then draws the edits itself.
    """
    mine = slide_edits(edits, slide_idx)
    if not mine:
        return None
    render_dir = _render_dir(pptx_path, slide_idx, mine)
    png = _png(render_dir, slide_idx)
    if not (png.exists() and png.stat().st_size > 0) and render:
        _render(pptx_path, mine, slide_idx, slide_count, render_dir)
    if png.exists() and png.stat().st_size > 0:
        return PA._public_url(png)
    return None


def _single_slide_copy(pptx_path: str, edits: Mapping[str, Any], slide_idx: int,
                       out: Path) -> None:
    """A copy of the deck holding only page ``slide_idx``, with its edits written in.

    PowerPoint takes ~6 s to open a freshly written copy of a whole deck and ~0.4 s to
    open one slide of it, so everything else is dropped — the slide's relationship too,
    or its part would still be saved and opened.
    """
    from pptx import Presentation
    from pptx.oxml.ns import qn

    from studio.template_fill.fill import write_text_overrides

    prs = Presentation(pptx_path)
    write_text_overrides(prs, dict(edits))
    ids = prs.slides._sldIdLst
    for position, entry in reversed(list(enumerate(list(ids)))):
        if position != slide_idx:
            ids.remove(entry)
            prs.part.drop_rel(entry.get(qn("r:id")))
    prs.save(str(out))


def _render(pptx_path: str, edits: Mapping[str, Any], slide_idx: int, slide_count: int,
            render_dir: Path) -> None:
    """Have PowerPoint draw page ``slide_idx`` with its edits, into ``render_dir``.

    The working copy lives in the system temp folder, not under ``assets/``: this project
    sits in OneDrive, and a file freshly written there is held by the sync client while
    PowerPoint tries to open it.
    """
    if os.environ.get("STUDIO_TEMPLATE_RENDERER", "").lower() == "none":
        return
    render_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qbr_edit_", ignore_cleanup_errors=True) as work:
        work_dir = Path(work)
        copy = work_dir / "page.pptx"
        try:
            _single_slide_copy(pptx_path, edits, slide_idx, copy)
            # Aspose when installed (as for the deck), else the warm PowerPoint.
            if not PA._render_with_aspose(str(copy), work_dir, 1, _WIDTH_PX, {0}):
                ppt_renderer.render(str(copy), work_dir, [0], width_px=_WIDTH_PX)
            drawn = work_dir / "slide-000.png"
            if drawn.exists() and drawn.stat().st_size > 0:
                shutil.move(str(drawn), str(_png(render_dir, slide_idx)))
        except Exception as exc:  # noqa: BLE001 — the canvas falls back to drawing the edit
            logger.warning("edited render failed for slide %d of %s: %s", slide_idx,
                           Path(pptx_path).name, exc)


__all__ = ["edited_slide_url", "slide_edits", "EDITED_DIR"]
