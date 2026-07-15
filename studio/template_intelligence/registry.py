"""Approved template configs — the governance seam for template onboarding.

Dict-dispatch registry (the codebase idiom): known templates resolve to an
approved :class:`BindingMapV2`; an unseen template gets a *draft* map — derived
deterministically from the existing slot/role inference, optionally enriched by
the layout agent — that stays unapproved until validation + human sign-off.
Either way ``validate_or_create_binding_map`` returns a map plus its validation
issues, so a template change produces explicit mapping feedback instead of
silent bad output (plan success criterion).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from logger import get_logger
from studio.template_intelligence.binding import (
    BindingIssue,
    BindingMapV2,
    from_manifest,
    from_static_map,
    validate_binding_map,
)
from studio.template_intelligence.descriptor import TemplateDescriptor

logger = get_logger(__name__)


@dataclass(frozen=True)
class TemplateConfig:
    """One governed template: identity + its binding map + approval status."""

    name: str
    path: str
    binding_map: BindingMapV2
    status: str = "draft"                  # draft | approved


_REGISTRY: Dict[str, Callable[[], TemplateConfig]] = {}


def register_template(name: str, builder: Callable[[], TemplateConfig]) -> None:
    _REGISTRY[name] = builder


def available_templates() -> List[str]:
    _bootstrap_static_maps()
    return sorted(_REGISTRY)


def get_template_config(name: str) -> TemplateConfig:
    _bootstrap_static_maps()
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise KeyError(f"no template config registered for {name!r}; "
                       f"have {available_templates()}") from None


_bootstrapped = False


def _bootstrap_static_maps() -> None:
    """Adapt every existing checked-in static map to an approved TemplateConfig.

    Keeps the current fixed-template export path working while V2 is introduced —
    the plan's default: preserve current templates until BindingMapV2 is approved.
    """
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    try:
        from studio.template_fill import binding_map as static
    except Exception as exc:  # noqa: BLE001 — governance layer must not break import
        logger.warning("template registry: static maps unavailable: %s", exc)
        return
    for name in static.available():
        def build(name=name) -> TemplateConfig:
            v2 = from_static_map(static.get_binding_map(name))
            return TemplateConfig(name=name, path=v2.template_path,
                                  binding_map=v2, status="approved")
        _REGISTRY.setdefault(name, build)


def _config_for_path(path: str) -> Optional[TemplateConfig]:
    """The approved config whose template file is ``path`` (name or path match)."""
    _bootstrap_static_maps()
    norm = str(Path(path)).replace("\\", "/")
    stem = Path(path).stem
    for name in sorted(_REGISTRY):
        cfg = _REGISTRY[name]()
        if str(Path(cfg.path)).replace("\\", "/") == norm or name == stem:
            return cfg
    return None


def validate_or_create_binding_map(
    descriptor: TemplateDescriptor,
    layout_intent=None,
    *,
    template_path: Optional[str] = None,
) -> Tuple[BindingMapV2, List[BindingIssue]]:
    """The pipeline step: an approved map when one exists, else a validated draft.

    Draft creation is code-free for a new template: deterministic slot/role
    inference (``derive_manifest``) produces the candidate bindings; the layout
    agent's intent (when provided) only fills still-unmapped slots with
    lower-confidence suggestions. The returned issues are the explicit feedback
    a new/changed template produces.
    """
    path = template_path or descriptor.path

    cfg = _config_for_path(path)
    if cfg is not None and cfg.status == "approved":
        issues = validate_binding_map(cfg.binding_map, descriptor)
        return cfg.binding_map, issues

    # Unseen template → deterministic draft (no code changes needed).
    from studio.template_fill.registry import derive_manifest

    _, manifest_bindings = derive_manifest(path)
    draft = from_manifest(Path(path).stem, path, manifest_bindings,
                          fingerprint=descriptor.fingerprint)

    if layout_intent is not None:
        draft = _merge_agent_suggestions(draft, descriptor, layout_intent)

    issues = validate_binding_map(draft, descriptor)
    logger.info("template registry: draft map for %s — %d binding(s), %d issue(s)",
                path, len(draft.bindings), len(issues))
    return draft, issues


def _merge_agent_suggestions(
    draft: BindingMapV2, descriptor: TemplateDescriptor, intent
) -> BindingMapV2:
    """Fill the draft's still-unmapped slots with agent-labelled suggestions.

    Deterministic inference always wins; the agent only annotates leftovers, so
    the merged map never gets *less* deterministic than the pure draft.
    """
    from dataclasses import replace as _replace

    merged = []
    for b in draft.bindings:
        if b.role is not None or b.treatment != "blank":
            merged.append(b)
            continue
        label = intent.role_of(b.slide_idx, b.shape_id)
        if label is not None and label.role in ("kpi", "commentary", "chart"):
            merged.append(_replace(
                b, role=f"{label.role}:{b.key}", confidence=label.confidence,
                source="agent", treatment="fill",
            ))
        else:
            merged.append(b)
    return _replace(draft, bindings=tuple(merged))
