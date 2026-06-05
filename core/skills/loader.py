"""Progressive skill loader (Phase 2).

`SkillLoader` reads all `*.md` files under `core/skills/` once at construction
time, parses their YAML frontmatter, and on each call returns ONLY the bodies
of skills that:

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

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - dependency-free fallback
    yaml = None


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

    def matches(self, flow: SkillFlow, scope: SkillScope, query: str) -> bool:
        if flow != self.flow and self.flow != "cross":
            return False
        if scope not in self.scope:
            return False
        if self.always:
            return True
        if not self.triggers:
            return False
        return any(_trigger_hit(trigger, query) for trigger in self.triggers)


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


@dataclass
class SkillLoader:
    """Reads `core/skills/*.md` once and serves them on demand."""

    skills_dir: Path = field(default_factory=lambda: Path(__file__).parent)
    _skills: list[Skill] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._skills = self._discover()

    def _discover(self) -> list[Skill]:
        skills: list[Skill] = []
        for md_path in sorted(self.skills_dir.glob("*.md")):
            if md_path.name.upper() == "README.MD":
                continue
            skill = self._parse(md_path)
            if skill is not None:
                skills.append(skill)
        return skills

    @staticmethod
    def _parse(path: Path) -> Optional[Skill]:
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
        triggers = meta.get("triggers") or []
        if isinstance(triggers, str):
            triggers = [triggers]
        return Skill(
            name=str(name),
            description=str(description),
            flow=str(flow),
            scope=tuple(scope),
            triggers=tuple(str(t) for t in triggers),
            always=bool(meta.get("always", False)),
            priority=int(meta.get("priority", 0)),
            body=body.strip("\n"),
            source=path,
        )

    def matching(
        self, flow: SkillFlow, scope: SkillScope, query: str
    ) -> list[Skill]:
        matched = [s for s in self._skills if s.matches(flow, scope, query)]
        # Higher priority first; stable on name as tiebreaker.
        matched.sort(key=lambda s: (-s.priority, s.name))
        return matched

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
    scalar and bracket-list forms used in `core/skills/*.md`.
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
