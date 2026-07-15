"""Template-tier QA — slots, charts, tables and binding-map health (Phase 6).

Pure functions over the materialized render fields (``model.materialize_fields``
output) and the V2 binding map. Severity policy:

  * a slot whose text still reads as a placeholder after fill → CRITICAL
    (silent bad output is the failure mode this plan exists to prevent);
  * a mapped slot whose data never resolved → WARNING (honest data gap);
  * intentionally blank / decorative / manual slots → INFO (recorded, allowed);
  * externally-linked (think-cell) charts → INFO (manual fill by design).
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from studio.qa.report import CRITICAL, INFO, WARNING, QAIssue
from studio.template_fill.slots import classify


def _slot_key(fld: Mapping[str, Any]) -> str:
    return f"{fld['slide_idx']}:{fld['shape_id']}:{'-'.join(str(p) for p in fld['where'])}"


def check_required_slots(
    fields: Mapping[str, Mapping[str, Any]],
    *,
    hidden_slides: Optional[List[int]] = None,
) -> List[QAIssue]:
    """Every mapped slot on a visible slide either filled or an explicit gap."""
    hidden = set(hidden_slides or [])
    issues: List[QAIssue] = []
    for key, fld in fields.items():
        if fld["slide_idx"] in hidden:
            continue
        role = fld.get("role")
        if role and not fld.get("filled"):
            issues.append(QAIssue(
                "slot_unfilled", WARNING,
                f"slot mapped to {role!r} has no resolved data — left as template placeholder",
                key))
        elif fld.get("filled") and classify(str(fld.get("text") or "")) is not None:
            issues.append(QAIssue(
                "slot_stale_placeholder", CRITICAL,
                f"slot marked filled but still reads as a placeholder: {str(fld.get('text'))[:40]!r}",
                key))
    return issues


def check_charts(
    fields: Mapping[str, Mapping[str, Any]],
    values: Mapping[str, Any],
) -> List[QAIssue]:
    """Chart slots must have their series payload; external charts are manual."""
    issues: List[QAIssue] = []
    for key, fld in fields.items():
        if fld.get("value_kind") != "series":
            continue
        role = fld.get("role")
        payload = values.get(role) if role else None
        if payload is None:
            issues.append(QAIssue(
                "chart_no_data", WARNING,
                "chart slot has no series payload — chart keeps the template's authored data",
                key))
            continue
        points = payload.get("points") if isinstance(payload, dict) else None
        if isinstance(points, list) and not points:
            issues.append(QAIssue(
                "chart_empty_series", CRITICAL,
                "chart payload resolved but contains zero data points", key))
        else:
            issues.append(QAIssue(
                "chart_data_ok", INFO,
                f"chart receives {len(points) if isinstance(points, list) else '?'} point(s)", key))
    return issues


def check_intentional_blanks(binding_map) -> List[QAIssue]:
    """Record every manual/decorative/blank slot so silence is auditable."""
    issues: List[QAIssue] = []
    for b in binding_map.intentionally_blank():
        issues.append(QAIssue(
            "intentionally_blank", INFO,
            f"slot left {b.treatment} by the binding map", b.key))
    return issues


def check_binding_health(binding_map, descriptor=None) -> List[QAIssue]:
    """Surface binding-map validation as QA issues (errors become critical)."""
    from studio.template_intelligence.binding import ERROR, validate_binding_map

    issues: List[QAIssue] = []
    for issue in validate_binding_map(binding_map, descriptor):
        severity = CRITICAL if issue.severity == ERROR else WARNING
        issues.append(QAIssue(f"binding_{issue.code}", severity, issue.message, issue.location))
    if not binding_map.approved:
        issues.append(QAIssue(
            "binding_unapproved", WARNING,
            f"binding map {binding_map.name!r} is a draft — activation needs human approval"))
    return issues
