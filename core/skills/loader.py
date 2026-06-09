"""Progressive skill loader (Phase 2; folder-catalog migration — step 6).

`SkillLoader` recursively reads every `*.skill.md` file under the catalog root
(`core/skills/catalog/<flow>/`) once at construction time, parses their YAML
frontmatter, resolves any `{{ref: refs/<file>.md#anchor}}` section includes in
the body, and on each call returns ONLY the bodies of skills that:

  1. Match the requested flow (`survey`, `gpr`, `gimmi`, or `cross` for shared).
  2. Have the requested scope in their `scope:` list (`planner`, `sql`,
     `response`, `chart`).
  3. Either declare `always: true` OR have at least one entry from `triggers:`
     appearing in the user query (case-insensitive substring match).

If nothing matches, `load(...)` returns `None` so the caller can fall back to
the legacy `core.rules.*` Python strings — zero-behavior-risk migration.

Frontmatter schema (all fields optional except name/description/flow/scope):

```markdown
---
name: survey-peer-average
description: Peer Average / peer score calculation rules for Survey flow.
flow: survey                  # survey | gpr | gimmi | cross
scope: [planner]              # planner | sql | response | chart  (list)
triggers: [peer, peer average, peer score, peers]
always: false                 # if true, triggers are ignored
priority: 50                  # higher = injected earlier in concatenated output
---

(rule body — plain text/markdown, injected verbatim into the prompt)
```
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from core.observability import log_event
from logger import get_logger

try:
    import yaml
except ImportError:  # pragma: no cover - dependency-free fallback
    yaml = None

logger = get_logger(__name__)


SkillScope = str  # "planner" | "sql" | "response" | "chart" | "pitch"
SkillFlow = str  # "survey" | "gpr" | "gimmi" | "cross"


@dataclass(frozen=True)
class Skill:
    """A single parsed skill file."""

    name: str
    description: str
    flow: SkillFlow
    scope: tuple[SkillScope, ...]
    triggers: tuple[str, ...]
    always: bool
    priority: int
    body: str
    source: Path
    negative_triggers: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    kind: str = ""
    risk_level: str = ""

    def applies(self, flow: SkillFlow, scope: SkillScope) -> bool:
        """Flow + scope compatibility, ignoring triggers.

        Used both as the first gate in `matches` and to decide whether a
        dependency pulled in via `requires` is valid for the current scope.
        """
        if flow != self.flow and self.flow != "cross":
            return False
        return scope in self.scope

    def positive_hit(self, query: str) -> bool:
        """True when this skill's own triggers fire (or it is always-on)."""
        if self.always:
            return True
        return any(_trigger_hit(t, query) for t in self.triggers)

    def negative_hit(self, query: str) -> bool:
        return any(_trigger_hit(t, query) for t in self.negative_triggers)

    def matches(self, flow: SkillFlow, scope: SkillScope, query: str) -> bool:
        if not self.applies(flow, scope):
            return False
        if self.always:
            # An always-on skill is unconditional; negative_triggers gate only
            # trigger-based matches (false-positive suppression), never always-on
            # safety/base skills.
            return True
        if not self.triggers:
            return False
        if not self.positive_hit(query):
            return False
        # A positive trigger fired — suppress it if a negative trigger also hits
        # (e.g. "competitor" fires peer-average, but "competitor product launch"
        # is not a peer-benchmark question).
        return not self.negative_hit(query)


@lru_cache(maxsize=512)
def _trigger_pattern(trigger: str) -> "re.Pattern[str]":
    """Word-boundary regex for a trigger phrase, built once per trigger.

    Plain substring matching fires on incidental overlaps — "mom" inside
    "momentum", "top" inside "stopped" / "top-of-mind", "re" inside "premium" —
    which loads the wrong analytical skill. Anchoring on word boundaries
    restricts a trigger to whole-word/phrase hits. Internal whitespace in a
    multi-word trigger spans hyphens/extra spaces so "year over year",
    "year-over-year", and "year  over  year" all match.

    A trailing optional inflection (`s`/`es`/`ed`/`ing`) preserves the plural and
    verb forms substring matching used to catch — so trigger "peer" still hits
    "peers", "competitor" hits "competitors", "rank" hits "ranking" — without
    re-admitting the incidental-substring false positives above ("momentum" still
    does NOT match "mom" because "entum" is not a valid suffix).
    """
    parts = [re.escape(tok) for tok in trigger.lower().split()]
    body = r"[\s\-]+".join(parts)
    # Lookarounds (not `\b`) so boundaries work next to non-word chars like "&".
    return re.compile(
        rf"(?<![a-z0-9]){body}(?:s|es|ed|ing)?(?![a-z0-9])", re.IGNORECASE
    )


def _trigger_hit(trigger: str, query: str) -> bool:
    trigger = trigger.strip()
    if not trigger:
        return False
    return _trigger_pattern(trigger).search(query) is not None


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """Coerce a frontmatter scalar/list field into a tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if v is not None)
    return (str(value),)


# ── section-anchor reference resolution ─────────────────────────────────────
#
# A skill body may externalise a section into a sibling `refs/<file>.md` and pull
# it back inline with a directive on its own line:
#
#     {{ref: refs/sow-denominator.md#denominator-contract}}
#
# The directive is replaced by the body of the matching heading section (the
# lines under that heading up to the next heading of the same-or-higher level).
# Paths are resolved relative to the skill's own directory and guarded so a ref
# can never escape the catalog root. Used for the few large skills (SoW,
# peer-average) whose shared rules would otherwise be duplicated.

_REF_DIRECTIVE = re.compile(
    r"^[ \t]*\{\{\s*ref:\s*(?P<path>[^#}\s]+)#(?P<anchor>[^}\s]+?)\s*\}\}[ \t]*$",
    re.MULTILINE,
)


class RefError(Exception):
    """A `{{ref: ...}}` directive that could not be resolved (bad path/anchor)."""


def _slugify(heading: str) -> str:
    """GitHub-style anchor slug: lowercase, spaces/underscores → hyphens."""
    text = heading.strip().lstrip("#").strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"[^a-z0-9\-]", "", text)


# Chart `chart_type` enum → the per-type detail ref under `catalog/chart/refs/`.
# `pie`/`donut` share one ref; `none` (and anything unknown) resolves to no detail
# so the two-phase chart node injects nothing extra.
_CHART_DETAIL_FILE = {
    "bar": "chart-bar",
    "line": "chart-line",
    "pie": "chart-pie-donut",
    "donut": "chart-pie-donut",
    "scatter": "chart-scatter",
    "waterfall": "chart-waterfall",
    "combo": "chart-combo",
}


@lru_cache(maxsize=64)
def _read_ref_file(resolved: str, mtime: float) -> str:
    """Whole-file body of a ref (no frontmatter), cached per path + mtime."""
    return Path(resolved).read_text(encoding="utf-8").strip("\n")


@lru_cache(maxsize=256)
def _ref_section(resolved: str, mtime: float, anchor: str) -> str:
    """Body of one heading section in a ref file.

    Cache key is (resolved path, file mtime, anchor) so an edited ref file is
    re-read on the next construction; the mtime component invalidates the entry
    when the file changes on disk.
    """
    lines = Path(resolved).read_text(encoding="utf-8").splitlines()
    target = anchor.strip().lower()
    captured: list[str] = []
    level: Optional[int] = None
    for line in lines:
        m = re.match(r"^(#+)\s+(.*)$", line)
        if level is None:
            if m and _slugify(m.group(2)) == target:
                level = len(m.group(1))
            continue
        # Inside the captured section — stop at the next same/higher heading.
        if m and len(m.group(1)) <= level:
            break
        captured.append(line)
    if level is None:
        raise RefError(f"anchor #{anchor} not found in {Path(resolved).name}")
    return "\n".join(captured).strip("\n")


def _resolve_refs(body: str, skill_dir: Path, root: Path) -> str:
    """Expand every `{{ref: ...}}` directive in ``body`` in place.

    Raises ``RefError`` for a missing file, a path that escapes ``root``, or an
    unknown anchor so authoring mistakes surface in ``validate()`` rather than
    silently shipping an empty rule.
    """
    if "{{ref:" not in body:
        return body
    root_resolved = root.resolve()

    def _sub(match: "re.Match[str]") -> str:
        rel, anchor = match.group("path"), match.group("anchor")
        resolved = (skill_dir / rel).resolve()
        if root_resolved != resolved and root_resolved not in resolved.parents:
            raise RefError(f"ref path {rel!r} escapes the catalog root")
        if not resolved.is_file():
            raise RefError(f"ref file {rel!r} does not exist")
        return _ref_section(str(resolved), resolved.stat().st_mtime, anchor)

    return _REF_DIRECTIVE.sub(_sub, body)


@dataclass
class SkillLoader:
    """Recursively reads the `core/skills/catalog/` tree and serves it on demand."""

    skills_dir: Path = field(
        default_factory=lambda: Path(__file__).parent / "catalog"
    )
    _skills: list[Skill] = field(default_factory=list, init=False)
    _by_name: dict[str, Skill] = field(default_factory=dict, init=False)
    _ref_errors: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._skills = self._discover()
        self._by_name = {s.name: s for s in self._skills}

    def _discover(self) -> list[Skill]:
        skills: list[Skill] = []
        root = self.skills_dir.resolve()
        # `*.skill.md` is the catalog convention; recurse so each flow lives in
        # its own subfolder. `refs/` bodies are pulled in via {{ref}} directives,
        # never discovered as standalone skills.
        for md_path in sorted(self.skills_dir.rglob("*.skill.md")):
            if "refs" in md_path.relative_to(self.skills_dir).parts:
                continue
            resolved = md_path.resolve()
            if root != resolved and root not in resolved.parents:
                # Defence-in-depth: a symlink that points outside the catalog.
                self._ref_errors.append(f"{md_path.name}: escapes catalog root")
                continue
            skill = self._parse(md_path)
            if skill is not None:
                skills.append(skill)
        return skills

    def _parse(self, path: Path) -> Optional[Skill]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        try:
            _, fm, body = text.split("---", 2)
        except ValueError:
            return None
        meta = _load_frontmatter(fm)
        name = meta.get("name")
        description = meta.get("description", "")
        flow = meta.get("flow")
        scope = meta.get("scope") or []
        if not name or not flow or not scope:
            return None
        if isinstance(scope, str):
            scope = [scope]
        body = body.strip("\n")
        try:
            body = _resolve_refs(body, path.parent, self.skills_dir)
        except RefError as exc:
            self._ref_errors.append(f"{path.name}: {exc}")
        return Skill(
            name=str(name),
            description=str(description),
            flow=str(flow),
            scope=tuple(scope),
            triggers=_as_str_tuple(meta.get("triggers")),
            always=bool(meta.get("always", False)),
            priority=int(meta.get("priority", 0)),
            body=body,
            source=path,
            negative_triggers=_as_str_tuple(meta.get("negative_triggers")),
            requires=_as_str_tuple(meta.get("requires")),
            conflicts_with=_as_str_tuple(meta.get("conflicts_with")),
            kind=str(meta.get("kind") or ""),
            risk_level=str(meta.get("risk_level") or ""),
        )

    def matching(
        self, flow: SkillFlow, scope: SkillScope, query: str
    ) -> list[Skill]:
        # 1. Base matches: own triggers fired (or always-on), minus negatives.
        base = [s for s in self._skills if s.matches(flow, scope, query)]
        selected: dict[str, Skill] = {s.name: s for s in base}

        # 2. Pull in `requires` dependencies (transitively) that are valid for
        #    this flow+scope, even if their own triggers did not fire — a metric
        #    skill's rules are incomplete without the rules it depends on (e.g.
        #    Share of Wallet needs the Marsh-market denominator rule).
        required_added: list[str] = []
        dangling: list[str] = []
        queue = list(base)
        while queue:
            skill = queue.pop()
            for dep_name in skill.requires:
                dep = self._by_name.get(dep_name)
                if dep is None:
                    dangling.append(dep_name)
                    continue
                if dep_name in selected or not dep.applies(flow, scope):
                    continue
                selected[dep_name] = dep
                required_added.append(dep_name)
                queue.append(dep)

        matched = sorted(selected.values(), key=lambda s: (-s.priority, s.name))

        # 3. Diagnostics: what fired, what was suppressed, what was pulled in,
        #    and any declared conflicts among the selected set.
        suppressed = [
            s.name
            for s in self._skills
            if s.applies(flow, scope)
            and not s.always
            and s.positive_hit(query)
            and s.negative_hit(query)
        ]
        conflicts = self._conflicts(matched)
        if matched or suppressed or dangling:
            log_event(
                logger,
                "skill_match",
                logging.DEBUG,
                node="skill_loader",
                flow=flow,
                scope=scope,
                matched=[s.name for s in matched],
                required_added=required_added,
                suppressed=suppressed,
                conflicts=conflicts,
                dangling_requires=dangling,
            )
        if conflicts:
            log_event(
                logger,
                "skill_conflict",
                logging.WARNING,
                node="skill_loader",
                flow=flow,
                scope=scope,
                conflicts=conflicts,
            )
        return matched

    @staticmethod
    def _conflicts(matched: list[Skill]) -> list[list[str]]:
        """Pairs of co-selected skills that declare a conflict (either direction).

        Per policy we keep both and only warn — contradictory rules are surfaced
        for authoring review, never silently dropped from the prompt.
        """
        names = {s.name for s in matched}
        pairs: list[list[str]] = []
        for s in matched:
            for other in s.conflicts_with:
                if other in names:
                    pair = sorted((s.name, other))
                    if pair not in pairs:
                        pairs.append(pair)
        return pairs

    def load(
        self, flow: SkillFlow, scope: SkillScope, query: str
    ) -> Optional[str]:
        """Return concatenated bodies of all matching skills, or None if none match."""
        matched = self.matching(flow, scope, query)
        if not matched:
            return None
        return self._render(matched)

    def load_many(
        self, flows: tuple[SkillFlow, ...] | list[SkillFlow], scope: SkillScope, query: str
    ) -> Optional[str]:
        """Like ``load`` but spans several flows, deduplicating shared skills.

        Used by multi-flow nodes (the 'both' combined-insight node and the pitch
        report synthesis) that draw on survey + gpr context at once. A `cross`
        skill matched under both flows is emitted only once, by name.
        """
        seen: dict[str, Skill] = {}
        for flow in flows:
            for skill in self.matching(flow, scope, query):
                seen.setdefault(skill.name, skill)
        if not seen:
            return None
        matched = sorted(seen.values(), key=lambda s: (-s.priority, s.name))
        return self._render(matched)

    @staticmethod
    def _render(skills: list[Skill]) -> str:
        return "\n\n".join(f"## {s.name}\n\n{s.body}" for s in skills)

    # Convenience helpers per scope.
    def planner(self, flow: SkillFlow, query: str) -> Optional[str]:
        return self.load(flow, "planner", query)

    def sql(self, flow: SkillFlow, query: str) -> Optional[str]:
        return self.load(flow, "sql", query)

    def response(self, flow: SkillFlow, query: str) -> Optional[str]:
        return self.load(flow, "response", query)

    def chart(self, flow: SkillFlow, query: str) -> Optional[str]:
        return self.load(flow, "chart", query)

    def pitch(self, flow: SkillFlow, query: str) -> Optional[str]:
        return self.load(flow, "pitch", query)

    def chart_detail(self, chart_type: str) -> Optional[str]:
        """Per-type chart guidance for a decided `chart_type`, or None.

        Phase two of the two-phase chart node: once the type is chosen (from the
        always-on `chart-type-selection` tree), only THAT type's detail body is
        injected — instead of dumping all six per-type skills every call. Bodies
        live under `catalog/chart/refs/` and are never discovered as skills.
        """
        stem = _CHART_DETAIL_FILE.get((chart_type or "").strip().lower())
        if not stem:
            return None
        path = (self.skills_dir / "chart" / "refs" / f"{stem}.md").resolve()
        root = self.skills_dir.resolve()
        if root != path and root not in path.parents:
            return None
        if not path.is_file():
            return None
        return _read_ref_file(str(path), path.stat().st_mtime)

    # Progressive disclosure: fetch a skill body on demand and enumerate what is
    # available, so an agent can pull a rule whose trigger never fired.
    def body(self, name: str) -> Optional[str]:
        """Full body of a skill by name, or None if unknown."""
        skill = self._by_name.get(name)
        return skill.body if skill else None

    def applicable(self, flow: SkillFlow, scope: SkillScope) -> list[Skill]:
        """Every skill valid for this flow+scope, ignoring triggers.

        This is the universe a `consult_skill` tool may draw from — the menu, as
        opposed to `matching()` which is what fired for this query.
        """
        skills = [s for s in self._skills if s.applies(flow, scope)]
        skills.sort(key=lambda s: (-s.priority, s.name))
        return skills

    # Authoring / CI guardrails.
    def validate(self) -> list[str]:
        """Return a list of skill-catalog issues (empty == healthy).

        Catches the mistakes that silently degrade matching: missing required
        frontmatter, duplicate names, and `requires`/`conflicts_with` pointing at
        skills that do not exist. Intended for a CI test, not the hot path.
        """
        issues: list[str] = list(self._ref_errors)
        seen: set[str] = set()
        known = set(self._by_name)
        for skill in self._skills:
            where = skill.source.name
            if not skill.name:
                issues.append(f"{where}: missing name")
            if not skill.flow:
                issues.append(f"{where}: missing flow")
            if not skill.scope:
                issues.append(f"{where}: missing scope")
            if not skill.always and not skill.triggers:
                issues.append(
                    f"{where}: {skill.name} has neither always:true nor triggers "
                    "(it can never match)"
                )
            if skill.name in seen:
                issues.append(f"{where}: duplicate skill name {skill.name!r}")
            seen.add(skill.name)
            for dep in skill.requires:
                if dep not in known:
                    issues.append(f"{where}: {skill.name} requires unknown skill {dep!r}")
            for other in skill.conflicts_with:
                if other not in known:
                    issues.append(
                        f"{where}: {skill.name} conflicts_with unknown skill {other!r}"
                    )
        return issues


_default_loader: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """Module-level singleton so each request reuses the parsed skill cache."""
    global _default_loader
    if _default_loader is None:
        _default_loader = SkillLoader()
    return _default_loader


def _load_frontmatter(text: str) -> dict[str, Any]:
    """Load the small YAML subset used by skill frontmatter.

    Prefer PyYAML when available. The fallback intentionally supports only the
    scalar and bracket-list forms used in `core/skills/catalog/**/*.skill.md`.
    """
    if yaml is not None:
        return yaml.safe_load(text) or {}

    meta: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = (
                [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]
                if inner
                else []
            )
        elif value.lower() in {"true", "false"}:
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value.strip("'\"")
    return meta
