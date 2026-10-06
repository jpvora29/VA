"""One warm, private PowerPoint for re-rendering edited slides.

``preview_assets._render_with_powerpoint`` starts PowerPoint, exports, and quits — the
right shape for rendering a deck once, and the wrong one for an author pressing Apply:
starting PowerPoint is 3.5 s warm and 8 s cold, and exporting the page is a fraction of
that. So edited pages are rendered by ONE instance kept alive on its own thread (COM
objects belong to the thread that made them), fed through a queue.

``DispatchEx`` is used as in the deck renderer, but PowerPoint is single-instance, so this
may be the author's own PowerPoint: presentations are opened read-only and windowless,
and it is quit (after ``IDLE_SECONDS`` without a request, or at interpreter exit) only
when it is invisible and holds nothing open. It is started again on the next request — and if a call fails (PowerPoint was closed under us), the
instance is thrown away and the request retried once on a fresh one.

``render`` returns False whenever PowerPoint is unavailable; callers then fall back.
"""
from __future__ import annotations

import atexit
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from logger import get_logger

logger = get_logger(__name__)

IDLE_SECONDS = 600          # quit PowerPoint after ten quiet minutes
REQUEST_TIMEOUT = 60        # never hold a callback longer than this


@dataclass
class _Request:
    pptx_path: str
    out_dir: Path
    pages: tuple
    width_px: int
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False


class _Worker:
    """The thread that owns the PowerPoint instance."""

    def __init__(self) -> None:
        self._requests: "queue.Queue[Optional[_Request]]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="ppt-renderer", daemon=True)
        self._thread.start()

    def submit(self, request: _Request) -> bool:
        self._requests.put(request)
        request.done.wait(REQUEST_TIMEOUT)
        return request.ok

    def stop(self) -> None:
        self._requests.put(None)

    def _run(self) -> None:
        try:
            import pythoncom  # type: ignore
        except Exception:   # noqa: BLE001 — no pywin32: every request answers False
            pythoncom = None
        if pythoncom is not None:
            pythoncom.CoInitialize()
        app = None
        try:
            while True:
                try:
                    request = self._requests.get(timeout=IDLE_SECONDS if app else None)
                except queue.Empty:
                    app = _quit(app)            # idle: give the memory back
                    continue
                if request is None:
                    break
                if pythoncom is None:
                    request.done.set()
                    continue
                app, request.ok = _serve(app, request)
                request.done.set()
        finally:
            _quit(app)
            if pythoncom is not None:
                pythoncom.CoUninitialize()


def _launch():
    import win32com.client  # type: ignore

    return win32com.client.DispatchEx("PowerPoint.Application")


def _quit(app):
    """Let go of PowerPoint — and quit it only when nobody else is using it.

    PowerPoint is a single-instance COM server: ``DispatchEx`` hands back the SAME
    process the author may have open on their desk. Quitting it then would close their
    presentations, so it is only quit when it is invisible and holds nothing open.
    """
    if app is not None:
        try:
            if not app.Visible and int(app.Presentations.Count) == 0:
                app.Quit()
        except Exception:   # noqa: BLE001 — it may already be gone
            pass
    return None


def _export(app, request: _Request) -> None:
    presentation = app.Presentations.Open(str(Path(request.pptx_path).resolve()),
                                          ReadOnly=True, WithWindow=False)
    try:
        setup = presentation.PageSetup
        height = int(request.width_px * float(setup.SlideHeight) / float(setup.SlideWidth or 1))
        for page in request.pages:
            if 0 <= page < int(presentation.Slides.Count):
                out = request.out_dir / f"slide-{page:03d}.png"
                presentation.Slides(page + 1).Export(str(out.resolve()), "PNG",
                                                     request.width_px, height)
    finally:
        presentation.Close()


def _serve(app, request: _Request):
    """``(app, ok)`` — the instance to keep, and whether the pages were written."""
    for attempt in (1, 2):
        try:
            app = app or _launch()
            _export(app, request)
            return app, True
        except Exception as exc:  # noqa: BLE001 — a dead instance: drop it, try once more
            logger.warning("ppt_renderer: render attempt %d failed for %s: %s",
                           attempt, Path(request.pptx_path).name, exc)
            app = _quit(app)
    return app, False


_lock = threading.Lock()
_worker: Optional[_Worker] = None


def _the_worker() -> _Worker:
    global _worker
    with _lock:
        if _worker is None or not _worker._thread.is_alive():
            _worker = _Worker()
        return _worker


def render(pptx_path: str, out_dir: Path, pages: Iterable[int], *, width_px: int = 1600) -> bool:
    """Export ``pages`` of ``pptx_path`` as ``out_dir/slide-NNN.png``. False if it could not."""
    out_dir.mkdir(parents=True, exist_ok=True)
    request = _Request(str(pptx_path), out_dir, tuple(pages), int(width_px))
    return _the_worker().submit(request)


@atexit.register
def _shutdown() -> None:
    if _worker is not None:
        _worker.stop()


__all__ = ["render", "IDLE_SECONDS"]
