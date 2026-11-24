"""What story an answer tells, and which evidence fills each part of it.

`story_sections.yaml` lists, per answer shape, the sections the writer's
contract asks for and the requirement keys (from `intents.yaml`) that fill each
one. This module parses it once per process and builds a `StoryPlan` for a turn:
every section of the shape, each marked fillable or carrying the reason it is
not.

Pure: nothing here retrieves, plans or writes. It answers one question the
graph never asked before — "does the evidence this turn will gather cover the
story its shape promises?" — so a missing section can be stated rather than
silently dropped.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.analysis.requirements import EvidenceContract, get_requirements
from logger import get_logger

logger = get_logger(__name__)

_STORY_PATH = Path(__file__).parent / "story_sections.yaml"

#: The shape used when a turn names none or an unknown one. Mirrors
#: `core.agents.common.answer_shape.DEFAULT_SHAPE` (pinned by a test) without
#: importing the agents package into the analysis layer.
DEFAULT_SHAPE = "analyst"

#: Section statuses.
FILLABLE = "fillable"  # the contract gathers evidence for it
DEFERRED = "deferred"  # the intent declares it, this turn's conditions excluded it
NOT_OWED = "not_owed"  # the shape promises it, the contract never asks for it
UNSUPPORTED = "unsupported"  # synthesis with nothing fillable to build on


@dataclass(frozen=True)
class StorySection:
    """One part of a shape's story, as declared in the YAML."""

    key: str
    label: str
    requirements: tuple[str, ...] = ()
    builds_on: tuple[str, ...] = ()
    required: bool = True

    @property
    def is_synthesis(self) -> bool:
        """Written from other sections, not from data."""
        return not self.requirements


@dataclass(frozen=True)
class PlannedSection:
    """A section of this turn's story, with whether it can be filled."""

    key: str
    label: str
    status: str
    required: bool = True
    requirements: tuple[str, ...] = ()
    reason: str = ""

    @property
    def fillable(self) -> bool:
        return self.status == FILLABLE

    @property
    def is_evidence(self) -> bool:
        """Filled from requirements (as opposed to a synthesis section)."""
        return bool(self.requirements)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StoryPlan:
    """Every section of the turn's shape, in reading order."""

    shape: str
    sections: tuple[PlannedSection, ...] = ()

    def requirements(self) -> tuple[str, ...]:
        """Requirement keys the fillable sections draw on, in section order."""
        return tuple(
            dict.fromkeys(
                key
                for section in self.sections
                if section.fillable
                for key in section.requirements
            )
        )

    def unfillable(self) -> tuple[PlannedSection, ...]:
        """Required sections this turn cannot fill, each with its reason."""
        return tuple(s for s in self.sections if s.required and not s.fillable)

    def as_dict(self) -> dict:
        return {"shape": self.shape, "sections": [s.as_dict() for s in self.sections]}


@dataclass(frozen=True)
class StoryLibrary:
    """Parsed `story_sections.yaml`."""

    shapes: Mapping[str, tuple[StorySection, ...]] = field(default_factory=dict)

    def resolve(self, shape: str | None) -> str:
        """The shape actually used: the named one, else the default."""
        return shape if shape in self.shapes else DEFAULT_SHAPE

    def sections_for(self, shape: str | None) -> tuple[StorySection, ...]:
        return self.shapes.get(self.resolve(shape), ())


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def parse_section(raw: Mapping[str, Any]) -> StorySection:
    return StorySection(
        key=str(raw.get("key") or "").strip(),
        label=str(raw.get("label") or raw.get("key") or "").strip(),
        requirements=tuple(str(k) for k in raw.get("requirements") or ()),
        builds_on=tuple(str(k) for k in raw.get("builds_on") or ()),
        required=bool(raw.get("required", True)),
    )


def section_problems(
    shape: str, sections: tuple[StorySection, ...], known_requirements: Iterable[str]
) -> tuple[str, ...]:
    """Config mistakes that would make a section silently never fill."""
    known = set(known_requirements)
    keys = {s.key for s in sections}
    problems = []
    for section in sections:
        problems += [
            f"{shape}.{section.key}: unknown requirement {key!r}"
            for key in section.requirements
            if key not in known
        ]
        problems += [
            f"{shape}.{section.key}: builds_on unknown section {key!r}"
            for key in section.builds_on
            if key not in keys
        ]
    return tuple(problems)


def load_story_library(
    path: Path = _STORY_PATH, known_requirements: Iterable[str] | None = None
) -> StoryLibrary:
    """Parse the YAML. A missing or broken file yields an empty library."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:  # noqa: BLE001 - config must not crash a turn
        logger.error("could not load %s: %s", path, exc)
        return StoryLibrary()
    known = tuple(
        known_requirements
        if known_requirements is not None
        else get_requirements().requirements
    )
    shapes = {}
    for shape, items in (raw.get("shapes") or {}).items():
        sections = tuple(parse_section(item or {}) for item in items or ())
        for problem in section_problems(shape, sections, known):
            logger.warning("story_sections.yaml: %s", problem)
        shapes[str(shape)] = sections
    return StoryLibrary(shapes)


_library: StoryLibrary | None = None


def get_story_library() -> StoryLibrary:
    """Process-wide singleton, parsed on first use."""
    global _library
    if _library is None:
        _library = load_story_library()
    return _library


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


def build_story_plan(
    shape: str | None,
    contract: EvidenceContract,
    *,
    library: StoryLibrary | None = None,
) -> StoryPlan:
    """The turn's story: each section of its shape, fillable or with a reason.

    Evidence sections are judged against the contract first; synthesis sections
    then follow from whether anything they build on can be filled. Output keeps
    the shape's reading order.
    """
    library = library or get_story_library()
    sections = library.sections_for(shape)
    evidence = {
        s.key: plan_evidence_section(s, contract)
        for s in sections
        if not s.is_synthesis
    }
    filled = {key for key, planned in evidence.items() if planned.fillable}
    planned = tuple(
        evidence.get(s.key) or plan_synthesis_section(s, filled) for s in sections
    )
    return StoryPlan(shape=library.resolve(shape), sections=planned)


def plan_evidence_section(
    section: StorySection, contract: EvidenceContract
) -> PlannedSection:
    """Fillable when the contract selects any of the section's requirements."""
    selected = tuple(key for key in section.requirements if contract.requires(key))
    if selected:
        return _planned(section, FILLABLE, selected)
    deferred = next(
        (r for r in contract.deferred if r.key in section.requirements), None
    )
    if deferred is not None:
        return _planned(section, DEFERRED, (deferred.key,), deferred.limitation)
    intent = contract.intent or "this question's"
    return _planned(
        section,
        NOT_OWED,
        section.requirements,
        f"The {intent} contract gathers none of: {', '.join(section.requirements)}.",
    )


def plan_synthesis_section(section: StorySection, filled: set) -> PlannedSection:
    """Fillable when anything it builds on is (or it builds on nothing)."""
    if not section.builds_on or filled.intersection(section.builds_on):
        return _planned(section, FILLABLE)
    return _planned(
        section,
        UNSUPPORTED,
        reason=f"Nothing to build on: {', '.join(section.builds_on)} cannot be filled.",
    )


def sections_left_open(story: StoryPlan, reached: Iterable[str]) -> tuple[str, ...]:
    """Fillable evidence sections that none of the `reached` requirements covers.

    `reached` is what a later stage actually has: the requirements the plan's
    steps were assigned, or the requirements the evidence satisfied.
    """
    have = set(reached)
    return tuple(
        s.key
        for s in story.sections
        if s.fillable and s.is_evidence and not have.intersection(s.requirements)
    )


def _planned(
    section: StorySection,
    status: str,
    requirements: tuple[str, ...] = (),
    reason: str = "",
) -> PlannedSection:
    return PlannedSection(
        key=section.key,
        label=section.label,
        status=status,
        required=section.required,
        requirements=requirements,
        reason=reason,
    )
