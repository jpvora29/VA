"""BindingMapV2 — reusable slot↔content mapping with provenance + validation (Phase 3).

Extends the fixed-template ``template_fill.binding_map.SlotBinding`` idea with the
fields the governed-onboarding flow needs: per-binding ``confidence`` and
``source`` (static | derived | agent | manual), a ``treatment`` that records
manual-only / decorative / intentionally-blank slots, and a map-level
``template_fingerprint`` + ``approved`` flag. Draft maps can be suggested by the
layout agent, but activation requires deterministic validation
(:func:`validate_binding_map`) plus the approved flag — the human gate.

``to_manifest()`` folds a map into the exact ``{slot, role, placeholder}`` dicts
``studio.template_fill.model.materialize_fields`` consumes, so the existing fill
and export path keeps working unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from studio.template_intelligence.descriptor import TemplateDescriptor, shape_ref

TREATMENTS = ("fill", "manual", "decorative", "blank")
SOURCES = ("static", "derived", "agent", "manual")

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class SlotBindingV2:
    """One template slot bound to a role — with provenance and confidence."""

    slide_idx: int
    shape_id: int
    where: Tuple[Any, ...] = ()            # ('para', i) | ('cell', r, c) | ('chart',)
    value_kind: str = "text"               # money | pct | int | rank | text | series
    token: str = ""                        # the placeholder text in the template
    role: Optional[str] = None             # data/semantic role; None ⇒ placeholder
    confidence: float = 1.0                # 1.0 for authored maps; agent maps lower
    source: str = "static"                 # see SOURCES
    treatment: str = "fill"                # see TREATMENTS

    @property
    def key(self) -> str:
        return f"{self.slide_idx}:{self.shape_id}:{'-'.join(str(p) for p in self.where)}"

    @property
    def ref(self) -> str:
        return shape_ref(self.slide_idx, self.shape_id)

    @property
    def fillable(self) -> bool:
        return self.treatment == "fill" and self.role is not None

    def to_manifest_item(self) -> Dict[str, Any]:
        """The dict ``model.materialize_fields`` expects (fill path unchanged)."""
        role = self.role if self.treatment == "fill" else None
        return {
            "slot": {
                "slide_idx": self.slide_idx, "shape_id": self.shape_id,
                "where": list(self.where), "token": self.token,
                "value_kind": self.value_kind, "context": "",
            },
            "role": role,
            "placeholder": role is None,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_idx": self.slide_idx, "shape_id": self.shape_id,
            "where": list(self.where), "value_kind": self.value_kind,
            "token": self.token, "role": self.role,
            "confidence": self.confidence, "source": self.source,
            "treatment": self.treatment,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SlotBindingV2":
        return cls(
            slide_idx=int(d["slide_idx"]), shape_id=int(d["shape_id"]),
            where=tuple(d.get("where", [])), value_kind=str(d.get("value_kind", "text")),
            token=str(d.get("token", "")), role=d.get("role"),
            confidence=float(d.get("confidence", 1.0)),
            source=str(d.get("source", "static")),
            treatment=str(d.get("treatment", "fill")),
        )


@dataclass(frozen=True)
class BindingMapV2:
    """A template's approved (or draft) slot mapping, pinned to a file fingerprint."""

    name: str
    template_path: str
    template_fingerprint: str = ""
    bindings: Tuple[SlotBindingV2, ...] = field(default_factory=tuple)
    approved: bool = False

    def manifest(self) -> List[Dict[str, Any]]:
        return [b.to_manifest_item() for b in self.bindings]

    def fillable(self) -> Tuple[SlotBindingV2, ...]:
        return tuple(b for b in self.bindings if b.fillable)

    def intentionally_blank(self) -> Tuple[SlotBindingV2, ...]:
        return tuple(b for b in self.bindings if b.treatment in ("blank", "decorative", "manual"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "template_path": self.template_path,
            "template_fingerprint": self.template_fingerprint,
            "approved": self.approved,
            "bindings": [b.to_dict() for b in self.bindings],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BindingMapV2":
        return cls(
            name=str(d["name"]), template_path=str(d.get("template_path", d.get("path", ""))),
            template_fingerprint=str(d.get("template_fingerprint", "")),
            bindings=tuple(SlotBindingV2.from_dict(b) for b in d.get("bindings", [])),
            approved=bool(d.get("approved", False)),
        )

    def write_json(self, path: str) -> str:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return str(out)

    @classmethod
    def read_json(cls, path: str) -> "BindingMapV2":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ── adapters from the existing flows ─────────────────────────────────────────


def from_static_map(bmap) -> BindingMapV2:
    """Adapt a checked-in ``template_fill.binding_map.BindingMap`` (already curated,
    so it arrives approved at full confidence)."""
    bindings = tuple(
        SlotBindingV2(
            slide_idx=b.slide_idx, shape_id=b.shape_id, where=tuple(b.where),
            value_kind=b.value_kind, token=b.token, role=b.role,
            confidence=1.0, source="static",
            treatment="fill" if b.role else "blank",
        )
        for b in bmap.bindings
    )
    return BindingMapV2(name=bmap.name, template_path=bmap.path,
                        bindings=bindings, approved=True)


def from_manifest(
    name: str, template_path: str, manifest_bindings, *, fingerprint: str = ""
) -> BindingMapV2:
    """Adapt a derived manifest (``registry.derive_manifest`` output) to V2.

    Derived maps come from deterministic inference, so mapped slots carry high
    (but not authored-level) confidence; placeholder slots are kept as blanks.
    """
    bindings = tuple(
        SlotBindingV2(
            slide_idx=b.slot.slide_idx, shape_id=b.slot.shape_id,
            where=tuple(b.slot.where), value_kind=b.slot.value_kind,
            token=b.slot.token, role=b.role,
            confidence=0.9 if b.role else 0.0,
            source="derived",
            treatment="fill" if b.role else "blank",
        )
        for b in manifest_bindings
    )
    return BindingMapV2(name=name, template_path=template_path,
                        template_fingerprint=fingerprint, bindings=bindings, approved=False)


def draft_from_intent(descriptor: TemplateDescriptor, intent) -> BindingMapV2:
    """Suggest a draft map for an unseen template from its layout intent.

    Agent-sourced and unapproved by construction: every binding carries the
    intent label's confidence, and activation still requires validation + human
    approval — the agent proposes, the deterministic layer disposes.
    """
    bindings: List[SlotBindingV2] = []
    for slide in descriptor.slides:
        for sh in slide.shapes:
            label = intent.role_of(slide.index, sh.shape_id)
            if label is None:
                continue
            if label.role in ("decorative", "manual"):
                bindings.append(SlotBindingV2(
                    slide.index, sh.shape_id, ("shape",), "text", sh.text[:40],
                    role=None, confidence=label.confidence, source="agent",
                    treatment="manual" if label.role == "manual" else "decorative",
                ))
                continue
            if label.role == "chart" and not sh.chart_external:
                bindings.append(SlotBindingV2(
                    slide.index, sh.shape_id, ("chart",), "series", sh.chart_type or "",
                    role="chart_data", confidence=label.confidence, source="agent",
                ))
                continue
            for i, para in enumerate(sh.paragraphs):
                if para.strip() and para.strip() in sh.tokens:
                    bindings.append(SlotBindingV2(
                        slide.index, sh.shape_id, ("para", i), label.expected_content,
                        para.strip(), role=f"{label.role}:{slide.index}:{sh.shape_id}:{i}",
                        confidence=label.confidence, source="agent",
                    ))
    return BindingMapV2(
        name=Path(descriptor.path).stem, template_path=descriptor.path,
        template_fingerprint=descriptor.fingerprint,
        bindings=tuple(bindings), approved=False,
    )


# ── deterministic validation ──────────────────────────────────────────────────


@dataclass(frozen=True)
class BindingIssue:
    code: str            # unknown_shape | duplicate_slot | missing_role | low_confidence | ...
    severity: str        # ERROR | WARNING
    message: str
    location: str = ""   # slot key


def validate_binding_map(
    bmap: BindingMapV2,
    descriptor: Optional[TemplateDescriptor] = None,
    *,
    min_confidence: Optional[float] = None,
) -> List[BindingIssue]:
    """Check a map for missing, duplicate, invalid and low-confidence bindings."""
    from studio.rules import load_rules

    floor = min_confidence if min_confidence is not None else load_rules().commentary.min_binding_confidence
    issues: List[BindingIssue] = []

    if not bmap.bindings:
        issues.append(BindingIssue("empty_map", ERROR, "binding map has no bindings"))

    seen: Dict[str, SlotBindingV2] = {}
    for b in bmap.bindings:
        if b.key in seen:
            issues.append(BindingIssue("duplicate_slot", ERROR,
                                       f"slot {b.key} bound more than once", b.key))
        seen[b.key] = b
        if b.treatment not in TREATMENTS:
            issues.append(BindingIssue("invalid_treatment", ERROR,
                                       f"unknown treatment {b.treatment!r}", b.key))
        if b.treatment == "fill" and not b.role:
            issues.append(BindingIssue("missing_role", WARNING,
                                       f"fill slot {b.key} has no role (stays a placeholder)", b.key))
        if b.fillable and b.confidence < floor:
            issues.append(BindingIssue("low_confidence", WARNING,
                                       f"slot {b.key} role {b.role!r} confidence {b.confidence:.2f} "
                                       f"below {floor:.2f} — needs review", b.key))
        if descriptor is not None and descriptor.shape(b.slide_idx, b.shape_id) is None:
            issues.append(BindingIssue("unknown_shape", ERROR,
                                       f"slot {b.key} references nonexistent shape "
                                       f"{shape_ref(b.slide_idx, b.shape_id)}", b.key))

    if descriptor is not None and bmap.template_fingerprint and descriptor.fingerprint \
            and bmap.template_fingerprint != descriptor.fingerprint:
        issues.append(BindingIssue(
            "fingerprint_mismatch", WARNING,
            "template file changed since this map was approved — re-validate mappings"))
    return issues


def has_errors(issues) -> bool:
    return any(i.severity == ERROR for i in issues)


def is_activatable(bmap: BindingMapV2, issues) -> bool:
    """Activation gate: deterministic validation passes AND a human approved it."""
    return bmap.approved and not has_errors(issues)


def approve(bmap: BindingMapV2) -> BindingMapV2:
    return replace(bmap, approved=True)
