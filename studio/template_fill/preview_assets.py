"""Preview assets for template-native Studio rendering.

The authoring UI needs browser-safe assets that come from the uploaded PPTX
template. This module keeps those generated files out of the template-fill model
itself and stores them under Dash's ``assets/`` folder so they can be referenced
directly from the preview.

Full-slide rendering is optional because local environments differ. When an
engine such as Aspose.Slides is installed, backgrounds are generated once and
cached. Without one, callers still get exact extracted picture assets and the
geometry preview remains available.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Iterable, List, Optional

from logger import get_logger

logger = get_logger(__name__)

DEFAULT_ROOT = Path("assets") / "studio_template_previews"
DOC_RENDER_VERSION = "ppt-rendered-background-v3-billions"


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_root() -> Path:
    return Path(os.environ.get("STUDIO_TEMPLATE_ASSET_ROOT", str(DEFAULT_ROOT)))


def template_cache_dir(template_path: str) -> Path:
    root = cache_root()
    return root / _sha1_file(template_path)[:16]


def _public_url(path: Path) -> Optional[str]:
    try:
        rel = path.resolve().relative_to((Path.cwd() / "assets").resolve())
    except ValueError:
        return None
    return "/assets/" + rel.as_posix()


def cache_picture(template_path: str, slide_idx: int, shape_id: int, ext: str, blob: bytes) -> Optional[str]:
    """Persist a picture shape and return a Dash-served URL when possible."""
    suffix = (ext or "png").lower().lstrip(".")
    if suffix in {"jpeg", "jpe"}:
        suffix = "jpg"
    out_dir = template_cache_dir(template_path) / "pictures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"slide-{slide_idx:03d}-shape-{shape_id}.{suffix}"
    if not out.exists() or out.stat().st_size != len(blob):
        out.write_bytes(blob)
    return _public_url(out)


def _cached_backgrounds(template_path: str, slide_count: int) -> List[Optional[str]]:
    out_dir = template_cache_dir(template_path) / "backgrounds"
    return _background_urls(out_dir, slide_count)


def _background_urls(out_dir: Path, slide_count: int) -> List[Optional[str]]:
    urls: List[Optional[str]] = []
    for idx in range(slide_count):
        path = out_dir / f"slide-{idx:03d}.png"
        urls.append(_public_url(path) if path.exists() and path.stat().st_size > 0 else None)
    return urls


def _render_with_aspose(pptx_path: str, out_dir: Path, slide_count: int, width_px: int) -> bool:
    try:
        import aspose.pydrawing as draw  # type: ignore
        import aspose.slides as slides  # type: ignore
    except Exception:
        return False

    try:
        with slides.Presentation(pptx_path) as presentation:
            ratio = float(presentation.slide_height) / float(presentation.slide_width or 1)
            image_size = draw.Size(width_px, int(width_px * ratio))
            for idx, slide in enumerate(presentation.slides):
                if idx >= slide_count:
                    break
                out = out_dir / f"slide-{idx:03d}.png"
                if out.exists():
                    continue
                with slide.get_image(image_size) as image:
                    image.save(str(out), slides.ImageFormat.PNG)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("template preview Aspose render failed for %s: %s", pptx_path, exc)
        return False


def _render_with_powerpoint(pptx_path: str, out_dir: Path, slide_count: int, width_px: int) -> bool:
    """Render slides with local Microsoft PowerPoint when available.

    This is intentionally isolated to Windows desktop environments. It gives the
    closest preview to what users will see in PowerPoint because it is PowerPoint.
    """
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except Exception:
        return False

    app = None
    presentation = None
    pythoncom.CoInitialize()
    try:
        # DispatchEx: a PRIVATE PowerPoint instance. Dispatch attaches to the user's
        # running PowerPoint — whose interactive session rejects COM calls while they
        # type/edit (every render fails → the canvas falls back to raw geometry), and
        # the Quit() below would try to close THEIR presentations.
        app = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = app.Presentations.Open(str(Path(pptx_path).resolve()), WithWindow=False)
        height_px = int(width_px * float(presentation.PageSetup.SlideHeight) / float(presentation.PageSetup.SlideWidth or 1))
        count = min(slide_count, int(presentation.Slides.Count))
        for idx in range(count):
            out = out_dir / f"slide-{idx:03d}.png"
            if out.exists():
                continue
            presentation.Slides(idx + 1).Export(str(out.resolve()), "PNG", width_px, height_px)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("template preview PowerPoint render failed for %s: %s", pptx_path, exc)
        return False
    finally:
        try:
            if presentation is not None:
                presentation.Close()
        except Exception:
            pass
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def _render_slides(pptx_path: str, out_dir: Path, slide_count: int, width_px: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if os.environ.get("STUDIO_TEMPLATE_RENDERER", "").lower() == "none":
        return
    if _render_with_aspose(pptx_path, out_dir, slide_count, width_px):
        return
    _render_with_powerpoint(pptx_path, out_dir, slide_count, width_px)


def ensure_slide_backgrounds(template_path: str, slide_count: int, *, width_px: int = 1600) -> List[Optional[str]]:
    """Return optional rendered-slide background URLs.

    The method is deliberately best-effort. It never fails template analysis just
    because a renderer is absent, and it avoids shelling out to unknown local
    commands. Installing Aspose.Slides enables high-fidelity backgrounds without
    changing the UI code.
    """
    cached = _cached_backgrounds(template_path, slide_count)
    if all(cached):
        return cached
    out_dir = template_cache_dir(template_path) / "backgrounds"
    out_dir.mkdir(parents=True, exist_ok=True)
    if os.environ.get("STUDIO_TEMPLATE_RENDERER", "").lower() != "none":
        _render_with_aspose(template_path, out_dir, slide_count, width_px)
    return _cached_backgrounds(template_path, slide_count)


def ensure_rendered_slide_backgrounds(pptx_path: str, slide_count: int, *, width_px: int = 1600) -> List[Optional[str]]:
    """Render a PPTX once, including PowerPoint fallback, and return cached URLs.

    This is used at generation/export time, not while navigating slides. Keeping
    PowerPoint startup out of the page render path makes next/previous instant
    when a cached image exists and falls back to geometry when it does not.
    """
    cached = _cached_backgrounds(pptx_path, slide_count)
    if all(cached):
        return cached
    out_dir = template_cache_dir(pptx_path) / "backgrounds"
    _render_slides(pptx_path, out_dir, slide_count, width_px)
    cached = _cached_backgrounds(pptx_path, slide_count)
    if not any(cached):
        # Nothing rendered at all — usually a transient COM failure. One retry
        # here beats a whole generation whose canvas falls back to raw geometry.
        logger.warning("template preview: no backgrounds rendered for %s — retrying once", pptx_path)
        _render_slides(pptx_path, out_dir, slide_count, width_px)
        cached = _cached_backgrounds(pptx_path, slide_count)
    return cached


def _doc_render_key(doc: dict, *, width_px: int) -> str:
    # NOTE: deliberately keyed on the data-driven values only, NOT on manual
    # overrides/added notes. A full PowerPoint re-render takes seconds, so making
    # it fire on every keystroke would freeze editing. The side-panel reflects edits
    # instantly and the export always applies them; the PNG stays a fast, stable
    # preview of the generated deck.
    payload = {
        "version": DOC_RENDER_VERSION,
        "template_path": doc.get("template_path"),
        "width_px": width_px,
        "values": doc.get("values", {}),
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def cached_doc_backgrounds(doc: dict, slide_count: int, *, width_px: int = 1600) -> List[Optional[str]]:
    """Return existing filled-document background URLs without rendering."""
    template_path = str(doc.get("template_path") or "")
    if not template_path:
        return [None] * slide_count
    render_dir = template_cache_dir(template_path) / "doc-backgrounds" / _doc_render_key(doc, width_px=width_px)
    return _background_urls(render_dir, slide_count)


def ensure_doc_backgrounds(doc: dict, slide_count: int, *, width_px: int = 1600) -> List[Optional[str]]:
    """Render the filled template document and return per-slide PNG URLs.

    This is the high-fidelity preview path. It renders a temporary PPTX produced by
    the same fill engine used for export, with hidden/reordered slides disabled so
    indices line up with the template analyzer's original slide order.
    """
    template_path = str(doc.get("template_path") or "")
    if not template_path:
        return [None] * slide_count
    render_dir = template_cache_dir(template_path) / "doc-backgrounds" / _doc_render_key(doc, width_px=width_px)
    urls = cached_doc_backgrounds(doc, slide_count, width_px=width_px)
    if all(urls):
        return urls

    if os.environ.get("STUDIO_TEMPLATE_RENDERER", "").lower() == "none":
        return urls

    filled_pptx = render_dir / "filled-preview.pptx"
    render_dir.mkdir(parents=True, exist_ok=True)
    try:
        from studio.template_fill.fill import fill_template

        preview_doc = dict(doc)
        preview_doc["hidden"] = []
        preview_doc["order"] = list(range(slide_count))
        fill_template(preview_doc, out_path=str(filled_pptx))
        _render_slides(str(filled_pptx), render_dir, slide_count, width_px)
    except Exception as exc:  # noqa: BLE001
        logger.warning("template preview filled-background render failed for %s: %s", template_path, exc)

    return _background_urls(render_dir, slide_count)


# ── cache lifecycle ──────────────────────────────────────────────────────────
#
# Every generated deck is a NEW file, so it hashes to a NEW directory of PNGs under
# ``assets/``. Nothing ever removed them: one directory per deck ever generated, each
# holding a full-resolution render of every slide. Left alone that grows without bound
# (1,735 directories / 114 MB on the machine this was written for), and Dash walks the
# whole assets tree to fingerprint it.
#
# So the cache is pruned to the decks that are still on screen. The SOURCE templates are
# kept: there are six of them, they never change between runs, and re-rendering them is
# the slow part of opening the canvas.


def _keep_dirs(paths: Iterable[str]) -> set:
    """The cache directory names for ``paths`` — skipping any file that is gone."""
    keep = set()
    for path in paths:
        try:
            keep.add(template_cache_dir(path).name)
        except OSError:                 # the .pptx was deleted; nothing to keep for it
            continue
    return keep


def source_template_paths() -> List[str]:
    """The author-made templates the deck is assembled from — always worth caching."""
    from studio.template_fill.binding_map import available, get_binding_map

    paths = []
    for name in available():
        try:
            path = get_binding_map(name).path
        except KeyError:                # a registered axis with no map — nothing to keep
            continue
        if Path(path).exists():
            paths.append(path)
    return paths


def _clear_readonly(func, path, _exc) -> None:
    """Retry a delete that failed on Windows' read-only attribute.

    Every file and directory under ``assets/`` here is marked read-only — OneDrive sets
    it on the folders it syncs — and ``rmtree`` refuses those with ``Access is denied``
    rather than with anything that names the cause. Clearing the bit and retrying is the
    documented remedy, and it is scoped to the one path that failed.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _remove(path: Path) -> bool:
    """Delete one cached directory. False — never an exception — if it will not go.

    A directory a browser still has open cannot be removed on Windows, and a preview that
    fails to be tidied away is not a reason to fail a generation.
    """
    try:
        shutil.rmtree(path, onexc=_clear_readonly)
        return True
    except OSError as exc:
        logger.debug("preview cache: could not remove %s (%s)", path, exc)
        return False


def _prune_doc_renders(template_dir: Path, keep: int = 1) -> int:
    """Drop all but the ``keep`` newest filled-document renders under one template.

    The source templates' own directories survive :func:`prune_cache` — they are six
    files that never change and are slow to render — but each EDIT of a document adds
    another full render inside one of them, keyed by the values it was rendered from. So
    the kept directory is trimmed from the inside as well.
    """
    parent = template_dir / "doc-backgrounds"
    if not parent.is_dir():
        return 0
    renders = sorted((d for d in parent.iterdir() if d.is_dir()),
                     key=lambda d: d.stat().st_mtime, reverse=True)
    return sum(1 for stale in renders[keep:] if _remove(stale))


def prune_cache(keep_paths: Iterable[str] = ()) -> int:
    """Delete every cached preview directory except the source templates' and ``keep_paths``'.

    Returns how many directories were removed.
    """
    root = cache_root()
    if not root.exists():
        return 0
    keep = _keep_dirs([*source_template_paths(), *keep_paths])
    removed = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name in keep:
            removed += _prune_doc_renders(child)
            continue
        removed += int(_remove(child))
    if removed:
        logger.info("preview cache: removed %d stale preview director(ies)", removed)
    return removed
