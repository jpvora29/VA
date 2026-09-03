"""TemplateDoc — the JSON-able document the app stores and edits.

Mirrors the overlay idea in ``studio/page/document.py``: a snapshot of the derived
manifest + resolved values, plus user overlays (per-slot text overrides, per-slot
role remaps, added free elements, hidden/reordered slides). ``materialize_fields``
folds it into a flat ``slot_key → field`` map that BOTH the on-screen geometry preview
and the fill engine consume — so the screen and the exported ``.pptx`` never diverge.
"""
import re
from typing import Any, Dict, List, Optional

from studio.template_fill import roles as R
from studio.template_fill.bindings import resolve_roles
from studio.template_fill.registry import active_template_path, derive_manifest

# A section-divider title like "Country (1)" / "Region (2)" / "Product (1)".
_DIVIDER = re.compile(r"^\s*([A-Za-z][A-Za-z ]*?)\s*\(\s*(\d+)\s*\)\s*$")
# Divider group → the GPR column whose selected-count decides how many blocks to keep.
_GROUP_COLUMN = {"country": "Country", "region": "Country", "product": "Product_Line",
                 "line": "Product_Line", "lob": "Product_Line"}


def _selected_count(result, column: str) -> Optional[int]:
    """How many values the user pinned for ``column`` (None = no filter → keep all)."""
    val = (getattr(result, "resolved_filters", None) or {}).get(column)
    if val is None:
        return None
    if isinstance(val, (list, tuple, set)):
        return len({v for v in val})
    return 1


def _hidden_blocks(template, result) -> List[int]:
    """Slide indices to drop: a divider block ``X (n)`` whose ``n`` exceeds the number
    of selected X's (e.g. a second Country block when one country is chosen)."""
    dividers = []  # (slide_idx, group_lower, number)
    for s in template.slides:
        m = _DIVIDER.match(s.title().strip())
        if m and len(s.title().strip()) <= 24:
            dividers.append((s.index, m.group(1).strip().lower(), int(m.group(2))))
    dividers.sort(key=lambda d: d[0])
    hidden: List[int] = []
    for k, (sidx, group, num) in enumerate(dividers):
        end = dividers[k + 1][0] if k + 1 < len(dividers) else len(template.slides)
        col = _GROUP_COLUMN.get(group)
        limit = _selected_count(result, col) if col else None
        if limit is not None and num > limit:
            hidden.extend(range(sidx, end))
    return sorted(set(hidden))


def _template_year(template) -> Optional[int]:
    """The template's hard-coded reporting year = the most common 20xx in its text."""
    from collections import Counter

    years: Counter = Counter()
    for s in template.slides:
        for sh in s.shapes:
            for tok in re.findall(r"\b(20\d{2})\b", sh.text):
                years[int(tok)] += 1
    return years.most_common(1)[0][0] if years else None


# ── seeding a TemplateDoc, one contributor at a time ─────────────────────────


def _value_contributors():
    """The modules that fill roles, in the order they get to write.

    Each is a ``provider(template, result) -> {role: value}``. Later entries win a
    clash, which is why they are a list rather than a set: the order IS the
    precedence rule. Imported inside the function because each provider imports
    back into this module for its own field materialisation.
    """
    from studio.template_fill import commentary, grids
    from studio.template_fill.survey import kpi as survey_kpi

    return (
        grids.grid_values,
        commentary.values,
        # The overall survey-score tile is gated on the run's data basis, so it fills
        # (or comes off) here for the same reason it does in the assembled deck.
        survey_kpi.values,
    )


class TemplateDocBuilder:
    """Builds the TemplateDoc for one result against one template.

    A TemplateDoc is a JSON-able snapshot — the derived manifest, the resolved
    values, and empty overlays for the author to edit into. Each ``add_*`` puts one
    of those layers in, so :func:`new_template_doc` reads as the layers stack.
    """

    def __init__(self, result, *, template_path: Optional[str] = None,
                 use_ai: bool = False) -> None:
        self._result = result
        self._path = template_path or active_template_path()
        self._template, self._bindings = derive_manifest(self._path, use_ai=use_ai)
        self._values: Dict[str, Any] = {}

    def add_role_values(self) -> "TemplateDocBuilder":
        """The scalar roles the bindings layer resolves straight off the result."""
        self._values.update(resolve_roles(self._result))
        return self

    def add_provider_values(self) -> "TemplateDocBuilder":
        """Grid rows, prose commentary and the survey tile, in contributor order.

        Deliberately NOT best-effort, unlike the same providers under
        :mod:`studio.template_fill.assemble`: this document is the one the author
        edits on screen, so a provider that cannot run is a bug to see, not a
        silently thinner page.
        """
        for provider in _value_contributors():
            self._values.update(provider(self._template, self._result))
        return self

    def add_template_year(self) -> "TemplateDocBuilder":
        """The year the template itself is authored around, when it states one."""
        year = _template_year(self._template)
        if year is not None:
            self._values["template_year"] = year
        return self

    def build(self) -> Dict[str, Any]:
        """The document: geometry, manifest, values, and empty author overlays."""
        return {
            "template_path": self._path,
            "width_emu": self._template.width_emu,
            "height_emu": self._template.height_emu,
            "n_slides": len(self._template.slides),
            "manifest": R.manifest_to_dicts(self._bindings),
            "values": self._values,
            "overrides": {},            # slot_key -> user text
            "map_overrides": {},        # slot_key -> role (remap)
            "added": {},                # slide_idx(str) -> [ {x,y,w,h,text} ]
            "hidden": _hidden_blocks(self._template, self._result),
            "order": list(range(len(self._template.slides))),
        }


def new_template_doc(result, *, template_path: Optional[str] = None,
                     use_ai: bool = False) -> Dict[str, Any]:
    """Seed a TemplateDoc from an ``OverallResult`` against the active template."""
    return (
        TemplateDocBuilder(result, template_path=template_path, use_ai=use_ai)
        .add_role_values()
        .add_provider_values()
        .add_template_year()
        .build()
    )


# ── folding it flat for the preview and the fill engine ──────────────────────


def _effective_role(doc, slot_key: str, role: Optional[str]) -> Optional[str]:
    return doc.get("map_overrides", {}).get(slot_key, role)


def materialize_fields(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Fold manifest ◅ values ◅ overrides → ``slot_key -> field`` for render + export.

    Each field: ``{slide_idx, shape_id, where, value_kind, token, role, placeholder,
    text, filled}``. ``filled`` is False for slots left as the template placeholder.
    """
    values = doc.get("values", {})
    overrides = doc.get("overrides", {})
    out: Dict[str, Dict[str, Any]] = {}
    for item in doc.get("manifest", []):
        b = R.Binding.from_dict(item)
        s = b.slot
        key = s.key
        role = _effective_role(doc, key, b.role)
        token = s.token
        text: Any = token
        filled = False
        if key in overrides:
            text = overrides[key]
            filled = True
        elif role and role in values:
            from studio.template_fill.render import render_token

            text = render_token(token, values[role], s.value_kind)
            filled = True
        out[key] = {
            "slide_idx": s.slide_idx,
            "shape_id": s.shape_id,
            "where": list(s.where),
            "value_kind": s.value_kind,
            "token": token,
            "role": role,
            "placeholder": b.placeholder and key not in overrides,
            "text": text,
            "filled": filled,
        }
    return out


def set_override(doc: Dict[str, Any], slot_key: str, text: str) -> Dict[str, Any]:
    doc = dict(doc)
    doc["overrides"] = {**doc.get("overrides", {}), slot_key: text}
    return doc


def add_element(doc: Dict[str, Any], slide_idx: int, element: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(doc)
    added = {k: list(v) for k, v in doc.get("added", {}).items()}
    added.setdefault(str(slide_idx), []).append(element)
    doc["added"] = added
    return doc
