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
from pathlib import Path
from typing import List, Optional

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
