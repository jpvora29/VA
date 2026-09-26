"""The QBR writer's playbook: SKILL.md guidance chosen for each section by its facts.

The writing rules used to be one long prompt, the same for every page: a decline and a
year of growth were briefed identically, and nothing told the writer that a
multi-country overall page should compare markets. The guidance now lives as skills in
``studio/skills/qbr-*/SKILL.md`` — the same library the deep-agent harness reads — and
each section is handed the ones its evidence calls for:

    always          qbr-icg-context, qbr-expert-voice
    premium_down    qbr-decline-diagnosis
    premium_up      qbr-growth-story
    multi_market    qbr-multi-market
    survey_lines    qbr-survey-link
    opportunity     qbr-opportunity

A skill declares its condition in its own frontmatter (``applies-when``), so adding one is
adding a file; a new CONDITION is one entry in :data:`CONDITIONS`. Selection is
deterministic — the model never decides which rules it is given.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterable, Mapping, Tuple

from logger import get_logger

logger = get_logger(__name__)

SKILL_PREFIX = "qbr-"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    applies_when: str
    order: int
    body: str


def skills_root() -> Path:
    return Path(__file__).resolve().parents[1] / "skills"


def _parse(text: str) -> Tuple[Dict[str, str], str]:
    """``(frontmatter, body)`` of a SKILL.md — a flat ``key: value`` header between ``---``."""
    if not text.startswith("---"):
        return {}, text.strip()
    _, head, body = text.split("---", 2)
    meta = {}
    for line in head.strip().splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip().lower()] = value.strip()
    return meta, body.strip()


@lru_cache(maxsize=1)
def library() -> Tuple[Skill, ...]:
    """Every QBR writing skill on disk, in their declared order. Read once per process."""
    found = []
    for path in sorted(skills_root().glob(f"{SKILL_PREFIX}*/SKILL.md")):
        try:
            meta, body = _parse(path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("commentary skills: could not read %s: %s", path, exc)
            continue
        found.append(Skill(
            name=meta.get("name") or path.parent.name,
            description=meta.get("description", ""),
            applies_when=meta.get("applies-when", "always"),
            order=int(meta.get("order", "100") or 100),
            body=body,
        ))
    return tuple(sorted(found, key=lambda s: (s.order, s.name)))


# ── when a skill applies: one predicate per condition name ───────────────────


def _premium_move(facts: Mapping[str, Any]) -> float:
    carrier = facts.get("carrier") or {}
    current, prior = carrier.get("current"), carrier.get("prior")
    if isinstance(current, (int, float)) and isinstance(prior, (int, float)):
        return float(current) - float(prior)
    return 0.0


def _has_opportunity(facts: Mapping[str, Any], ids: FrozenSet[str]) -> bool:
    """A peer gap, headroom or an absent segment in the evidence the section was given."""
    return any(i in ("peer.gap", "peer.gap_value", "headroom") or ".absent." in i for i in ids)


Condition = Callable[[Mapping[str, Any], FrozenSet[str]], bool]

CONDITIONS: Mapping[str, Condition] = {
    "always": lambda facts, ids: True,
    "premium_down": lambda facts, ids: _premium_move(facts) < 0,
    "premium_up": lambda facts, ids: _premium_move(facts) > 0,
    "multi_market": lambda facts, ids: len(facts.get("markets") or []) >= 2,
    "survey_lines": lambda facts, ids: any(i.startswith("survey.line.") for i in ids),
    "opportunity": _has_opportunity,
}


def select(facts: Mapping[str, Any], fact_ids: Iterable[str] = ()) -> Tuple[Skill, ...]:
    """The skills this section calls for, in the library's order.

    ``facts`` is the section's raw fact dict (direction, markets); ``fact_ids`` the ids its
    evidence pack actually carries — a skill about survey scores is only handed over when
    there are survey facts the writer can cite.
    """
    ids = frozenset(fact_ids or ())
    chosen = []
    for skill in library():
        rule = CONDITIONS.get(skill.applies_when)
        if rule is None:
            logger.warning("commentary skills: %s names an unknown condition %r",
                           skill.name, skill.applies_when)
            continue
        if rule(facts or {}, ids):
            chosen.append(skill)
    return tuple(chosen)


def playbook(facts: Mapping[str, Any], fact_ids: Iterable[str] = ()) -> str:
    """The skills for a section as one prompt block (empty when the library is missing)."""
    skills = select(facts, fact_ids)
    if not skills:
        return ""
    parts = [f"### SKILL {s.name} — {s.description}\n{s.body}" for s in skills]
    return ("PLAYBOOK — how an Insurer Consulting Leader writes this section. Follow these "
            "skills; where one conflicts with the evidence rules above, the evidence rules "
            "win.\n\n" + "\n\n".join(parts))
