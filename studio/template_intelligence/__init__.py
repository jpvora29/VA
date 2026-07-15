"""Template intelligence — descriptor, layout intent, BindingMapV2, governance.

Implements Phases 1–3 of the QBR Studio Template Intelligence plan: deterministic
PPTX parsing (`parse_pptx`), semantic layout labelling with a validated agent seam
(`layout_agent`), a reusable binding-map schema with provenance (`binding`), and
the approved-template registry (`registry`).
"""
from __future__ import annotations

from studio.template_intelligence.binding import (
    BindingIssue,
    BindingMapV2,
    SlotBindingV2,
    draft_from_intent,
    from_manifest,
    from_static_map,
    is_activatable,
    validate_binding_map,
)
from studio.template_intelligence.descriptor import (
    ShapeDescriptor,
    SlideDescriptor,
    TemplateDescriptor,
    shape_ref,
)
from studio.template_intelligence.layout_agent import (
    LayoutIntent,
    ShapeRoleLabel,
    SlidePurpose,
    detect_layout_intent,
    detect_layout_intent_deterministic,
    detect_layout_intent_sync,
    validate_layout_intent,
)
from studio.template_intelligence.parse_pptx import descriptor_from_template, parse_template
from studio.template_intelligence.registry import (
    TemplateConfig,
    available_templates,
    get_template_config,
    validate_or_create_binding_map,
)

__all__ = [
    "TemplateDescriptor", "SlideDescriptor", "ShapeDescriptor", "shape_ref",
    "parse_template", "descriptor_from_template",
    "LayoutIntent", "SlidePurpose", "ShapeRoleLabel",
    "detect_layout_intent", "detect_layout_intent_sync",
    "detect_layout_intent_deterministic", "validate_layout_intent",
    "BindingMapV2", "SlotBindingV2", "BindingIssue",
    "from_static_map", "from_manifest", "draft_from_intent",
    "validate_binding_map", "is_activatable",
    "TemplateConfig", "available_templates", "get_template_config",
    "validate_or_create_binding_map",
]
