"""Tests for the progressive skill loader's rich-schema behavior.

Covers the additions on top of trigger matching: `requires` dependency
auto-loading, `negative_triggers` false-positive suppression, `conflicts_with`
detection, frontmatter `validate()`, and a regression guard that the live
catalog still loads and that Share of Wallet pulls in the Marsh-market rule.

Run:  pytest tests/test_skill_loader.py -q -o pythonpath=.
"""
from __future__ import annotations

from pathlib import Path

from core.skills.loader import SkillLoader, get_skill_loader


def _write(dir_: Path, name: str, frontmatter: str, body: str = "rule body") -> None:
    # Catalog convention is `*.skill.md` (recursive discovery); coerce the short
    # fixture names ("sow.md") so these unit tests exercise the real glob.
    stem = name[:-3] if name.endswith(".md") else name
    (dir_ / f"{stem}.skill.md").write_text(
        f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8"
    )


# ── requires ────────────────────────────────────────────────────────────────


def test_requires_pulls_in_dependency_even_without_its_trigger(tmp_path: Path):
    _write(
        tmp_path,
        "sow.md",
        "name: sow\ndescription: d\nflow: gpr\nscope: [planner]\n"
        "triggers: [share of wallet]\nrequires: [marsh]\npriority: 80",
    )
    _write(
        tmp_path,
        "marsh.md",
        "name: marsh\ndescription: d\nflow: gpr\nscope: [planner]\n"
        "triggers: [marsh book]\npriority: 90",
    )
    loader = SkillLoader(skills_dir=tmp_path)
    names = [s.name for s in loader.matching("gpr", "planner", "zurich share of wallet")]
    # `marsh` never had its own trigger fire, but SoW requires it.
    assert names == ["marsh", "sow"]  # priority-ordered


def test_requires_respects_scope(tmp_path: Path):
    # Dependency only valid for `sql` scope must NOT be injected into `planner`.
    _write(
        tmp_path,
        "a.md",
        "name: a\ndescription: d\nflow: gpr\nscope: [planner]\n"
        "triggers: [foo]\nrequires: [b]",
    )
    _write(
        tmp_path,
        "b.md",
        "name: b\ndescription: d\nflow: gpr\nscope: [sql]\ntriggers: [bar]",
    )
    loader = SkillLoader(skills_dir=tmp_path)
    names = [s.name for s in loader.matching("gpr", "planner", "foo")]
    assert names == ["a"]


# ── negative_triggers ───────────────────────────────────────────────────────


def test_negative_trigger_suppresses_a_positive_hit(tmp_path: Path):
    _write(
        tmp_path,
        "peer.md",
        "name: peer\ndescription: d\nflow: gpr\nscope: [planner]\n"
        "triggers: [competitor]\nnegative_triggers: [competitor product]",
    )
    loader = SkillLoader(skills_dir=tmp_path)
    assert loader.matching("gpr", "planner", "vs competitor premium")  # fires
    assert not loader.matching("gpr", "planner", "competitor product launch")  # killed


def test_negative_trigger_does_not_affect_always_on(tmp_path: Path):
    _write(
        tmp_path,
        "base.md",
        "name: base\ndescription: d\nflow: gpr\nscope: [planner]\n"
        "always: true\nnegative_triggers: [anything]",
    )
    loader = SkillLoader(skills_dir=tmp_path)
    assert [s.name for s in loader.matching("gpr", "planner", "anything")] == ["base"]


# ── conflicts_with ──────────────────────────────────────────────────────────


def test_conflicts_keep_both_and_are_detected(tmp_path: Path):
    _write(
        tmp_path,
        "x.md",
        "name: x\ndescription: d\nflow: gpr\nscope: [planner]\n"
        "always: true\nconflicts_with: [y]",
    )
    _write(
        tmp_path,
        "y.md",
        "name: y\ndescription: d\nflow: gpr\nscope: [planner]\nalways: true",
    )
    loader = SkillLoader(skills_dir=tmp_path)
    names = sorted(s.name for s in loader.matching("gpr", "planner", "q"))
    assert names == ["x", "y"]  # policy: warn, keep both
    assert loader._conflicts(loader.matching("gpr", "planner", "q")) == [["x", "y"]]


# ── validate ────────────────────────────────────────────────────────────────


def test_validate_flags_dangling_requires(tmp_path: Path):
    _write(
        tmp_path,
        "a.md",
        "name: a\ndescription: d\nflow: gpr\nscope: [planner]\n"
        "triggers: [foo]\nrequires: [nope]",
    )
    loader = SkillLoader(skills_dir=tmp_path)
    issues = loader.validate()
    assert any("requires unknown skill 'nope'" in i for i in issues)


# ── live catalog regressions ────────────────────────────────────────────────


def test_live_catalog_is_valid():
    assert get_skill_loader().validate() == []


def test_body_and_applicable_for_progressive_disclosure(tmp_path: Path):
    _write(
        tmp_path,
        "a.md",
        "name: a\ndescription: triggered one\nflow: gpr\nscope: [planner]\n"
        "triggers: [foo]",
        body="body-a",
    )
    _write(
        tmp_path,
        "b.md",
        "name: b\ndescription: dormant one\nflow: gpr\nscope: [planner]\n"
        "triggers: [bar]",
        body="body-b",
    )
    loader = SkillLoader(skills_dir=tmp_path)
    # body() fetches any skill on demand, regardless of triggers.
    assert loader.body("b") == "body-b"
    assert loader.body("missing") is None
    # applicable() is the full flow+scope menu (the disclosure universe); a query
    # that only fires `foo` still lists `b` as available-on-demand.
    applicable = {s.name for s in loader.applicable("gpr", "planner")}
    matched = {s.name for s in loader.matching("gpr", "planner", "foo")}
    assert applicable == {"a", "b"}
    assert (applicable - matched) == {"b"}


def test_live_share_of_wallet_pulls_in_marsh_market():
    names = [
        s.name
        for s in get_skill_loader().matching("gpr", "planner", "Zurich share of wallet in Canada")
    ]
    assert "gpr-share-of-wallet" in names
    assert "gpr-marsh-market" in names  # via requires, not its own trigger


def test_migrated_domain_skills_carry_rich_schema_and_operative_rules():
    """Lock in the body migration: the key domain/metric skills must keep their
    rich frontmatter AND the concrete rules the rails depend on."""
    loader = get_skill_loader()
    rich = [
        "gpr-share-of-wallet",
        "gpr-share-of-portfolio",
        "gpr-marsh-market",
        "gpr-peer-average",
        "survey-peer-average",
        "gimmi-market-rate",
        "cross-sql-readonly-safety",
        "cross-response-confidentiality",
    ]
    for name in rich:
        skill = loader._by_name[name]
        assert skill.kind, f"{name} lost its kind"
        assert skill.risk_level, f"{name} lost its risk_level"
        assert "## " in skill.body, f"{name} lost its section structure"

    # Operative rules that MUST survive any future re-edit.
    assert "NULLIF(denominator, 0)" in loader._by_name["gpr-share-of-wallet"].body
    assert "peer_group AS" in loader._by_name["gpr-peer-average"].body
    assert "multiplying the decimal by 100" in loader._by_name["gimmi-market-rate"].body
    assert "VACUUM" in loader._by_name["cross-sql-readonly-safety"].body


def test_default_timeframe_skills_fire_without_any_time_words():
    """A query naming NO year must still receive the latest-year default rule.

    The rule used to live only in the trigger-gated `*-timeframe` skills, whose
    triggers are time words — so the no-year case (its own target case) never
    loaded it. The extracted always-on skills close that gap.
    """
    loader = get_skill_loader()
    query = "What is Zurich's premium in Canada?"  # no time reference at all
    for flow, scope in (("gpr", "planner"), ("gpr", "sql"), ("survey", "planner"), ("survey", "sql")):
        names = [s.name for s in loader.matching(flow, scope, query)]
        assert f"{flow}-default-timeframe" in names, (flow, scope, names)
        # The trigger-gated detail skill must NOT fire — no time words present.
        assert f"{flow}-timeframe" not in names, (flow, scope, names)
