"""Explicit, checked-in binding maps — the fixed-template replacement for inference.

Templates are now author-made and fixed, so the old ``analyze → detect slots → infer
roles`` heuristic (brittle, cached by content-hash) is replaced by a **static** map per
template: a curated list of :class:`SlotBinding` saying *exactly* which shape/cell on
which slide carries which data role. No runtime detection, no heuristics, fully
deterministic.

Two registration paths, one dispatch table (``_REGISTRY``):
  * **data maps** — curated JSON under ``maps/`` (produced by ``tools/generate_binding_map.py``
    then hand-edited) are auto-discovered and registered by filename;
  * **code maps** — anything built in Python registers itself with the ``@template(name)``
    decorator (the self-registering dict-dispatch the codebase favours).

``get_binding_map(name)`` returns the (cached) :class:`BindingMap`; ``manifest()`` folds it
into the same ``slot/role`` dicts the existing :func:`studio.template_fill.model.materialize_fields`
already consumes, so the fill engine is unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)

_MAPS_DIR = Path(__file__).parent / "maps"


@dataclass(frozen=True)
class SlotBinding:
    """One fillable place in a fixed template, bound to a data role (or left as placeholder).

    Mirrors the runtime fields of the old ``slots.Slot`` + ``roles.Binding`` pair, minus the
    inference-only ``context`` — the mapping is now authored, not derived.
    """

    slide_idx: int
    shape_id: int
    where: Tuple[Any, ...]          # ('para', i) | ('cell', r, c) | ('chart',)
    value_kind: str                 # money | pct | int | rank | text | series
    token: str                      # the placeholder text in the template (e.g. "$xx,xxxm")
    role: Optional[str] = None      # data role to fill; None ⇒ leave the placeholder

    @property
    def placeholder(self) -> bool:
        return self.role is None

    @property
    def key(self) -> str:
        return f"{self.slide_idx}:{self.shape_id}:{'-'.join(str(p) for p in self.where)}"

    def to_manifest_item(self) -> Dict[str, Any]:
        """The ``{slot, role, placeholder}`` dict ``model.materialize_fields`` expects."""
        return {
            "slot": {
                "slide_idx": self.slide_idx,
                "shape_id": self.shape_id,
                "where": list(self.where),
                "token": self.token,
                "value_kind": self.value_kind,
                "context": "",
            },
            "role": self.role,
            "placeholder": self.placeholder,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_idx": self.slide_idx,
            "shape_id": self.shape_id,
            "where": list(self.where),
            "value_kind": self.value_kind,
            "token": self.token,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SlotBinding":
        return cls(
            slide_idx=int(d["slide_idx"]),
            shape_id=int(d["shape_id"]),
            where=tuple(d.get("where", [])),
            value_kind=str(d.get("value_kind", "text")),
            token=str(d.get("token", "")),
            role=d.get("role"),
        )


@dataclass(frozen=True)
class BindingMap:
    """A fixed template's identity (``name``), its ``.pptx`` path, and its slot bindings."""

    name: str
    path: str
    bindings: Tuple[SlotBinding, ...] = field(default_factory=tuple)

    def manifest(self) -> List[Dict[str, Any]]:
        """Fold to the manifest dicts the fill engine consumes."""
        return [b.to_manifest_item() for b in self.bindings]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "path": self.path,
                "bindings": [b.to_dict() for b in self.bindings]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BindingMap":
        return cls(
            name=str(d["name"]),
            path=str(d["path"]),
            bindings=tuple(SlotBinding.from_dict(b) for b in d.get("bindings", [])),
        )

    def write_json(self, path: Optional[str] = None) -> str:
        out = Path(path) if path else _MAPS_DIR / f"{self.name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return str(out)


# ── registry / dispatch ──────────────────────────────────────────────────────
_REGISTRY: Dict[str, Callable[[], BindingMap]] = {}


def template(name: str) -> Callable[[Callable[[], BindingMap]], Callable[[], BindingMap]]:
    """Register a binding-map builder under ``name`` (self-registering dict dispatch).

    Use for code-built maps::

        @template("overall")
        def _overall() -> BindingMap:
            return BindingMap("overall", "template/overall.pptx", (...))
    """
    def deco(builder: Callable[[], BindingMap]) -> Callable[[], BindingMap]:
        _REGISTRY[name] = builder
        return builder
    return deco


def _discover_json_maps() -> None:
    """Register a loader for every curated ``maps/<name>.json`` not already registered."""
    if not _MAPS_DIR.exists():
        return
    for jf in _MAPS_DIR.glob("*.json"):
        name = jf.stem
        _REGISTRY.setdefault(name, lambda jf=jf: BindingMap.from_dict(json.loads(jf.read_text(encoding="utf-8"))))


@lru_cache(maxsize=None)
def get_binding_map(name: str) -> BindingMap:
    """The (cached) :class:`BindingMap` for ``name``. Raises ``KeyError`` if unknown."""
    _discover_json_maps()
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise KeyError(f"no binding map registered for template {name!r}; "
                       f"have {available()}") from None


def available() -> List[str]:
    """Every registered template name (data + code maps)."""
    _discover_json_maps()
    return sorted(_REGISTRY)


def template_path(name: str) -> str:
    return get_binding_map(name).path
