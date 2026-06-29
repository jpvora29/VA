"""Live validation + auto-fix for a filled TemplateDoc.

Fixes the "10 errors that never get re-checked" problem: issues are computed
**live** from the current (edited) doc every call — never frozen at build time — so
resolving a slot makes its issue disappear on the next render. ``auto_fix`` repairs
the auto-fixable categories deterministically; the caller then re-runs ``validate_doc``
and the count actually drops.

Categories:
  * ``unfilled``   — a slot mapped to a role whose value didn't resolve (data gap, warn).
  * ``blanked``    — a mapped slot a user override emptied (auto-fixable error).
  * ``stale``      — a slot marked filled but whose text is still a placeholder token
                     (e.g. ``xx.x``) — should never happen; flagged as error.
"""
from __future__ import annotations

from typing import Any, Dict, List

from studio.template_fill import roles as R
from studio.template_fill.model import materialize_fields, set_override
from studio.template_fill.slots import classify


def _is_placeholderish(text: str) -> bool:
    return classify(str(text or "")) is not None


def validate_doc(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Recompute issues from the current doc. Each issue is auto-fixable or not."""
    fields = materialize_fields(doc)
    values = doc.get("values", {})
    overrides = doc.get("overrides", {})
    issues: List[Dict[str, Any]] = []

    for key, fld in fields.items():
        role = fld.get("role")
        # A mapped slot that a user override emptied → restore from data (auto-fixable).
        if role and key in overrides and not str(overrides[key]).strip():
            issues.append(_issue(fld, "error", "blanked",
                                 "Mapped value was cleared — restore from data.", True))
            continue
        # Mapped to a role but the value never resolved → genuine data gap.
        if role and not fld["filled"] and role in (R.ROLE_SUBJECT,) + _DATA_ROLES:
            if role not in values and f"{role}" not in values:
                issues.append(_issue(fld, "warn", "unfilled",
                                     f"No data resolved for '{role}'.", False))
            continue
        # Filled, yet the text still looks like a placeholder → stale.
        if fld["filled"] and _is_placeholderish(fld["text"]):
            issues.append(_issue(fld, "error", "stale",
                                 "Value still reads as a placeholder.", True))
    return issues


_DATA_ROLES = (
    R.ROLE_MARSH_GWP, R.ROLE_MARSH_GWP_YOY, R.ROLE_CARRIER_GWP, R.ROLE_CARRIER_GWP_YOY,
    R.ROLE_SOW_PCT, R.ROLE_SOW_YOY, R.ROLE_RANK, R.ROLE_RANK_YOY, R.ROLE_GROWTH_BUBBLE,
)


def _issue(fld, severity, category, message, auto_fixable) -> Dict[str, Any]:
    return {
        "slide_idx": fld["slide_idx"],
        "slot_key": f"{fld['slide_idx']}:{fld['shape_id']}:{'-'.join(str(p) for p in fld['where'])}",
        "role": fld.get("role"),
        "severity": severity,
        "category": category,
        "message": message,
        "auto_fixable": auto_fixable,
    }


def auto_fix(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Repair every auto-fixable issue deterministically; return a new doc."""
    issues = validate_doc(doc)
    values = doc.get("values", {})
    out = dict(doc)
    for iss in issues:
        if not iss.get("auto_fixable"):
            continue
        if iss["category"] == "blanked":
            # Drop the emptying override so the resolved value shows again.
            ov = dict(out.get("overrides", {}))
            ov.pop(iss["slot_key"], None)
            out["overrides"] = ov
        elif iss["category"] == "stale":
            role = iss.get("role")
            if role and role in values:
                out = set_override(out, iss["slot_key"], str(values[role]))
    return out


def summary(doc: Dict[str, Any]) -> Dict[str, int]:
    issues = validate_doc(doc)
    return {
        "total": len(issues),
        "errors": sum(1 for i in issues if i["severity"] == "error"),
        "warnings": sum(1 for i in issues if i["severity"] == "warn"),
        "auto_fixable": sum(1 for i in issues if i["auto_fixable"]),
    }
