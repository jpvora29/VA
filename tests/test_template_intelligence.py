"""Template intelligence (plan Phases 1–3): descriptor stability, layout intent
validation, BindingMapV2 adapters + governance.

Covers the plan's template tests: current templates parse, shape references are
stable across repeated runs, the layout agent cannot return nonexistent ids,
low-confidence mappings are flagged, and a new template produces a draft map
without code changes.
"""
from __future__ import annotations

import os

import pytest

os.environ["STUDIO_AI"] = "off"          # deterministic: no LLM in tests

from studio.template_intelligence import (  # noqa: E402
    BindingMapV2,
    LayoutIntent,
    ShapeRoleLabel,
    SlidePurpose,
    TemplateDescriptor,
    available_templates,
    detect_layout_intent_sync,
    from_static_map,
    parse_template,
    validate_binding_map,
    validate_layout_intent,
    validate_or_create_binding_map,
)
from studio.template_intelligence.binding import (  # noqa: E402
    SlotBindingV2,
    approve,
    has_errors,
    is_activatable,
)
from studio.template_intelligence.layout_agent import SHAPE_ROLES, SLIDE_PURPOSES  # noqa: E402

TEMPLATES = [
    "template/overall_template.pptx",
    "template/product_template.pptx",
    "template/country_template.pptx",
    "template/qbr_template.pptx",
]


@pytest.fixture(scope="module")
def overall() -> TemplateDescriptor:
    return parse_template("template/overall_template.pptx")


# ── Phase 1: descriptor ───────────────────────────────────────────────────────


@pytest.mark.parametrize("path", TEMPLATES)
def test_current_templates_parse(path):
    d = parse_template(path)
    assert d.slide_count > 0
    assert d.width_emu > 0 and d.height_emu > 0
    assert d.fingerprint
    assert all(s.shapes for s in d.slides)


def test_shape_references_stable_across_runs(overall):
    again = parse_template("template/overall_template.pptx")
    assert overall.to_dict() == again.to_dict()
    assert overall.shape_refs() == again.shape_refs()


def test_descriptor_round_trips_through_json(overall):
    assert TemplateDescriptor.from_dict(overall.to_dict()) == overall


# ── Phase 2: layout intent ────────────────────────────────────────────────────


def test_layout_intent_is_deterministic_and_in_vocab(overall):
    a = detect_layout_intent_sync(overall)
    b = detect_layout_intent_sync(overall)
    assert a == b
    assert all(p.purpose in SLIDE_PURPOSES for p in a.slides)
    assert all(r.role in SHAPE_ROLES for r in a.shapes)
    assert len(a.slides) == overall.slide_count


def test_layout_agent_cannot_return_nonexistent_ids(overall):
    fake = LayoutIntent(
        slides=(SlidePurpose(999, "swot", 0.9),
                SlidePurpose(0, "not_a_purpose", 0.9),
                SlidePurpose(0, "cover", 2.5)),
        shapes=(ShapeRoleLabel(0, 999_999, "kpi", "money", 0.9),
                ShapeRoleLabel(999, 1, "kpi", "money", 0.9)),
    )
    cleaned, rejected = validate_layout_intent(fake, overall)
    assert len(rejected) == 4                       # fake slide, fake purpose, 2 fake shapes
    assert [p.slide_idx for p in cleaned.slides] == [0]
    assert cleaned.slides[0].confidence == 1.0      # clamped into [0, 1]
    assert cleaned.shapes == ()


# ── Phase 3: BindingMapV2 ─────────────────────────────────────────────────────


def test_static_maps_adapt_to_v2_and_stay_approved():
    from studio.template_fill.binding_map import get_binding_map

    v1 = get_binding_map("overall")
    v2 = from_static_map(v1)
    assert v2.approved
    assert len(v2.bindings) == len(v1.bindings)
    # The manifest fold matches what the fill engine already consumes.
    assert len(v2.manifest()) == len(v1.manifest())
    assert {m["slot"]["shape_id"] for m in v2.manifest()} == \
           {m["slot"]["shape_id"] for m in v1.manifest()}


def test_validation_flags_unknown_duplicate_and_low_confidence(overall):
    real = overall.slides[0].shapes[0]
    dup = SlotBindingV2(0, real.shape_id, ("para", 0), "money", "$xx", role="a")
    bad = BindingMapV2(
        name="bad", template_path=overall.path,
        bindings=(
            dup,
            dup,                                                     # duplicate slot
            SlotBindingV2(0, 999_999, ("para", 0), "money", "$xx", role="b"),   # unknown shape
            SlotBindingV2(1, overall.slides[1].shapes[0].shape_id, ("para", 1),
                          "pct", "x%", role="c", confidence=0.2, source="agent"),  # low confidence
        ),
    )
    issues = validate_binding_map(bad, overall)
    codes = {i.code for i in issues}
    assert {"duplicate_slot", "unknown_shape", "low_confidence"} <= codes
    assert has_errors(issues)


def test_activation_requires_validation_and_approval(overall):
    real = overall.slides[0].shapes[0]
    draft = BindingMapV2(
        name="draft", template_path=overall.path,
        bindings=(SlotBindingV2(0, real.shape_id, ("para", 0), "money", "$xx", role="kpi"),),
    )
    issues = validate_binding_map(draft, overall)
    assert not has_errors(issues)
    assert not is_activatable(draft, issues)         # unapproved draft never activates
    assert is_activatable(approve(draft), issues)    # human approval + clean validation


def test_approved_template_resolves_without_issues(overall):
    intent = detect_layout_intent_sync(overall)
    bmap, issues = validate_or_create_binding_map(
        overall, intent, template_path="template/overall_template.pptx")
    assert bmap.approved and bmap.name == "overall"
    assert not has_errors(issues)


def test_new_template_gets_draft_map_without_code_changes():
    # qbr_template has no checked-in static map — the onboarding path must still
    # produce a validated draft purely from deterministic inference + the agent seam.
    d = parse_template("template/qbr_template.pptx")
    intent = detect_layout_intent_sync(d)
    bmap, issues = validate_or_create_binding_map(
        d, intent, template_path="template/qbr_template.pptx")
    assert not bmap.approved                          # a draft, pending human approval
    assert len(bmap.bindings) > 0
    assert bmap.template_fingerprint == d.fingerprint
    assert not has_errors(issues)


def test_registry_lists_existing_static_templates():
    names = available_templates()
    assert {"overall", "product", "country"} <= set(names)


def test_binding_map_round_trips_through_json(tmp_path, overall):
    intent = detect_layout_intent_sync(overall)
    bmap, _ = validate_or_create_binding_map(overall, intent,
                                             template_path=overall.path)
    p = bmap.write_json(str(tmp_path / "map.json"))
    assert BindingMapV2.read_json(p) == bmap
