"""Active-template selection + cached manifest derivation.

The active template is a setting (default: the starter ``template/qbr_template.pptx``);
a user can drop a different ``.pptx`` under ``template/`` and select it. Analysis +
role inference are cached by file content-hash so re-selecting an already-seen template
is instant — and no code anywhere knows slide indices in advance, so switching template
simply re-runs ``analyze → detect → infer``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Tuple

from logger import get_logger
from studio.template_fill import roles as R
from studio.template_fill import slots as S
from studio.template_fill.analyze import Template, analyze

logger = get_logger(__name__)

_DEFAULT = "template/qbr_template.pptx"
_active: str = _DEFAULT
_cache: Dict[str, Tuple[Template, List[R.Binding]]] = {}


def active_template_path() -> str:
    return _active


def set_active_template(path: str) -> None:
    global _active
    _active = str(path)


def list_templates() -> List[str]:
    """Every ``.pptx`` available under the ``template/`` folder."""
    folder = Path("template")
    return sorted(str(p).replace("\\", "/") for p in folder.glob("*.pptx")) if folder.exists() else []


def _hash(path: str) -> str:
    p = Path(path)
    h = hashlib.sha1()
    h.update(p.read_bytes())
    return h.hexdigest()


def derive_manifest(path: str, *, use_ai: bool = False) -> Tuple[Template, List[R.Binding]]:
    """``analyze → detect slots → infer roles`` for ``path``, cached by content-hash."""
    key = _hash(path) + ("+ai" if use_ai else "")
    cached = _cache.get(key)
    if cached is not None:
        return cached
    from studio.template_fill import commentary, grids

    template = analyze(path)
    bindings = R.infer(S.detect(template), use_ai=use_ai)
    bindings = grids.augment(template, bindings)
    bindings = commentary.augment(template, bindings)
    logger.info("template_fill: derived %d slot(s), %d mapped, from %s",
                len(bindings), sum(1 for b in bindings if not b.placeholder), path)
    self = (template, bindings)
    _cache[key] = self
    return self
