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


def new_template_doc(result, *, template_path: Optional[str] = None, use_ai: bool = False) -> Dict[str, Any]:
    """Seed a TemplateDoc from an ``OverallResult`` against the active template."""
    path = template_path or active_template_path()
    template, bindings = derive_manifest(path, use_ai=use_ai)
    values = resolve_roles(result)
    tyear = _template_year(template)
    if tyear is not None:
        values["template_year"] = tyear
    return {
        "template_path": path,
        "width_emu": template.width_emu,
        "height_emu": template.height_emu,
        "n_slides": len(template.slides),
        "manifest": R.manifest_to_dicts(bindings),
        "values": values,
        "overrides": {},            # slot_key -> user text
        "map_overrides": {},        # slot_key -> role (remap)
        "added": {},                # slide_idx(str) -> [ {x,y,w,h,text} ]
        "hidden": _hidden_blocks(template, result),
        "order": list(range(len(template.slides))),
    }


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
