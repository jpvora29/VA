"""Step-6 guardrail: the folder-catalog migration is behaviour-neutral.

Proves the live `core/skills/catalog/<flow>/*.skill.md` tree loads the same set
of skills the flat catalog did (snapshot in `migration_baseline.json`, captured
just before the move), that `validate()` is clean, that `{{ref: ...}}` section
anchors resolve, and that a ref can never escape the catalog root.

Run:  pytest tests/skills/test_catalog_migration.py -q -o pythonpath=.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.skills.loader import RefError, SkillLoader, _resolve_refs, get_skill_loader

_BASELINE = json.loads(
    (Path(__file__).parent / "migration_baseline.json").read_text(encoding="utf-8")
)
_FLOWS = ("gpr", "survey", "gimmi", "cross")
_SCOPES = ("planner", "sql", "response", "chart", "pitch")

# Intentional deltas applied AFTER the (byte-neutral) folder move. The baseline is
# the immutable pre-migration snapshot; these record what later feature work
# changed so the parity tests stay meaningful instead of being silenced.
#   - the six per-type chart skills became `catalog/chart/refs/*.md` bodies,
#     fetched on demand by the two-phase chart node (no longer always-loaded);
#   - three bodies gained new operative rules (chart two-phase note + timeframe);
#   - the gpr/survey response skills gained the [STORY ARC] narrative-funnel block
#     (2026-06: executive storytelling across all routes);
#   - the default-timeframe rule was extracted from the trigger-gated timeframe
#     skills into two tiny ALWAYS-ON skills (2026-06): a query naming no year
#     never fired the time-word triggers, so the "default to latest year" rule
#     was missing exactly in its own target case.
_REMOVED_SKILLS = frozenset(
    {
        "chart-bar",
        "chart-combo",
        "chart-line",
        "chart-pie-donut",
        "chart-scatter",
        "chart-waterfall",
    }
)
# name -> the flow/scope slots the post-baseline skill applies to.
_ADDED_SKILLS: dict[str, tuple[str, ...]] = {
    "gpr-default-timeframe": ("gpr/planner", "gpr/sql"),
    "survey-default-timeframe": ("survey/planner", "survey/sql"),
}
_EDITED_BODIES = frozenset(
    {
        "chart-type-selection",
        "gpr-timeframe",
        "survey-timeframe",
        "gpr-response-formatting",
        "survey-response-analysis",
    }
)


def _applicable_snapshot(loader: SkillLoader) -> dict[str, list[str]]:
    snap: dict[str, list[str]] = {}
    for flow in _FLOWS:
        for scope in _SCOPES:
            names = sorted(s.name for s in loader.applicable(flow, scope))
            if names:
                snap[f"{flow}/{scope}"] = names
    return snap


def _expected_applicable() -> dict[str, list[str]]:
    """Baseline applicable set minus removed chart skills, plus later additions."""
    expected: dict[str, list[str]] = {}
    for key, names in _BASELINE["applicable"].items():
        kept = [n for n in names if n not in _REMOVED_SKILLS]
        if kept:
            expected[key] = sorted(kept)
    for name, slots in _ADDED_SKILLS.items():
        for slot in slots:
            expected[slot] = sorted(expected.get(slot, []) + [name])
    return expected


# ── catalog shape ───────────────────────────────────────────────────────────


def test_skill_set_is_baseline_minus_extracted_chart_skills():
    loader = get_skill_loader()
    names = {s.name for s in loader._skills}
    assert names == (set(_BASELINE["body_sha256"]) - _REMOVED_SKILLS) | set(
        _ADDED_SKILLS
    )
    assert (
        len(loader._skills)
        == _BASELINE["total"] - len(_REMOVED_SKILLS) + len(_ADDED_SKILLS)
        == 32
    )
    # Every skill came from a `*.skill.md` file under the catalog root, and each
    # flow lives in its own subfolder (recursive discovery, not a flat glob).
    root = (Path(__file__).resolve().parents[2] / "core" / "skills" / "catalog")
    for skill in loader._skills:
        assert skill.source.name.endswith(".skill.md")
        assert root in skill.source.resolve().parents


def test_validate_is_clean():
    assert get_skill_loader().validate() == []


def test_loaded_set_per_flow_scope_matches_baseline_minus_extracted():
    assert _applicable_snapshot(get_skill_loader()) == _expected_applicable()


def test_unedited_skill_bodies_byte_identical_to_pre_migration():
    """Bodies untouched by later feature work must still match the move snapshot —
    proves the migration and the chart/timeframe edits changed nothing else."""
    loader = get_skill_loader()
    for s in loader._skills:
        if s.name in _EDITED_BODIES or s.name in _ADDED_SKILLS:
            continue
        digest = hashlib.sha256(s.body.encode("utf-8")).hexdigest()
        assert digest == _BASELINE["body_sha256"][s.name], f"{s.name} body drifted"


# ── section-anchor references ───────────────────────────────────────────────


def test_section_anchor_resolves_and_directive_is_gone():
    body = get_skill_loader()._by_name["gpr-share-of-wallet"].body
    assert "{{ref:" not in body  # directive expanded
    assert "Marsh-book (market) premium for the SAME" in body  # ref content inlined


def test_ref_resolution_round_trips(tmp_path: Path):
    (tmp_path / "refs").mkdir()
    (tmp_path / "refs" / "shared.md").write_text(
        "# Rule One\n\nfirst rule body\n\n# Rule Two\n\nsecond rule body\n",
        encoding="utf-8",
    )
    out = _resolve_refs(
        "intro\n\n{{ref: refs/shared.md#rule-two}}\n\noutro",
        skill_dir=tmp_path,
        root=tmp_path,
    )
    assert out == "intro\n\nsecond rule body\n\noutro"


def test_ref_path_escape_is_rejected(tmp_path: Path):
    catalog = tmp_path / "catalog" / "gpr"
    catalog.mkdir(parents=True)
    (tmp_path / "secret.md").write_text("# X\n\nsecret\n", encoding="utf-8")
    try:
        _resolve_refs(
            "{{ref: ../../secret.md#x}}",
            skill_dir=catalog,
            root=tmp_path / "catalog",
        )
    except RefError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("path escape was not rejected")


def test_unknown_anchor_surfaces_in_validate(tmp_path: Path):
    flow = tmp_path / "gpr"
    refs = flow / "refs"
    refs.mkdir(parents=True)
    (refs / "r.md").write_text("# Present\n\nbody\n", encoding="utf-8")
    (flow / "a.skill.md").write_text(
        "---\nname: a\ndescription: d\nflow: gpr\nscope: [planner]\nalways: true\n---\n"
        "\n{{ref: refs/r.md#absent}}\n",
        encoding="utf-8",
    )
    loader = SkillLoader(skills_dir=tmp_path)
    assert any("absent" in i for i in loader.validate())


def test_refs_files_are_not_discovered_as_skills():
    # `refs/*.md` are ref bodies (no `.skill.md`), never standalone skills.
    names = {s.name for s in get_skill_loader()._skills}
    assert "gpr-sow-definition" not in names
    assert names.isdisjoint(_REMOVED_SKILLS)  # chart per-type bodies are refs now


# ── two-phase chart details ─────────────────────────────────────────────────


def test_chart_detail_returns_per_type_body_for_every_enum():
    loader = get_skill_loader()
    expected = {
        "bar": "[BAR CHART",
        "line": "[LINE CHART",
        "pie": "[PIE / DONUT CHART",
        "donut": "[PIE / DONUT CHART",  # pie + donut share one ref
        "scatter": "[SCATTER PLOT",
        "waterfall": "[WATERFALL CHART",
        "combo": "[COMBO CHART",
    }
    for chart_type, head in expected.items():
        body = loader.chart_detail(chart_type)
        assert body and body.startswith(head), chart_type


def test_chart_detail_none_and_unknown_return_none():
    loader = get_skill_loader()
    assert loader.chart_detail("none") is None
    assert loader.chart_detail("nonsense") is None
    assert loader.chart_detail("") is None


def test_chart_scope_no_longer_dumps_all_per_type_skills():
    # The always-on chart set is now just the decision tree + field mapping
    # (+ flow field-priority); the six per-type guides arrive on demand.
    loader = get_skill_loader()
    assert {s.name for s in loader.applicable("cross", "chart")} == {
        "chart-type-selection",
        "chart-field-mapping",
    }
