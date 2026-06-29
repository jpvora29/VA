"""Template-fill: understand ANY .pptx dynamically and fill it with data.

The studio's template-driven mode. Nothing here is keyed to a specific template
file — an analyzer introspects whatever ``.pptx`` is active, slot-detection finds
the fillable units, role-inference maps them to a fixed data vocabulary, the
binder resolves that vocabulary from ``studio.compute``, and the fill engine
clones the template and writes the values in (leaving everything it cannot map as
a placeholder).

    analyze(path) → Template            (geometry + content of every shape)
        slots.detect(template)          (fillable units, by token shape)
        roles.infer(template, slots)    (slot → role | placeholder = the manifest)
    bindings.resolve_roles(result)      (role → value, from real analytics)
    model.materialize_fields(doc)       (manifest ◅ values ◅ user overrides)
    fill.fill_template(...)             (clone the .pptx, write values, keep placeholders)
    validate.validate_doc(doc)          (live issues) / auto_fix(doc)
"""
from __future__ import annotations

from studio.template_fill.analyze import Template, analyze
from studio.template_fill.fill import fill_template
from studio.template_fill.model import materialize_fields, new_template_doc
from studio.template_fill.registry import active_template_path, derive_manifest

__all__ = [
    "Template",
    "analyze",
    "fill_template",
    "materialize_fields",
    "new_template_doc",
    "active_template_path",
    "derive_manifest",
]
