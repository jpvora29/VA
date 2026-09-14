"""What a question is entitled to be answered with.

`intents.yaml` declares, per analytical intent, the evidence that makes an answer
complete. This module is the typed read-only view of it, mirroring
`core.definitions.loader` and `core.registry.loader`: the YAML is the source of
truth, this parses it once per process and answers questions about it with pure
functions.

The point of naming requirements at all is that "the data could not support it"
and "nobody asked for it" stop being the same outcome. A requirement that is not
satisfied becomes a stated limitation, which the verifier can check for and a
reader can act on. A requirement that was never selected is simply absent.

Nothing here retrieves, computes, or decides whether a requirement IS satisfied —
that is the planner's and the validator's job. This module only says what was
asked of the turn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

import yaml

from logger import get_logger

logger = get_logger(__name__)

_INTENTS_PATH = Path(__file__).parent / "intents.yaml"

#: Datasets a requirement can be drawn from.
GPR = "gpr"
SURVEY = "survey"

#: Condition names `intents.yaml` may gate a conditional requirement on. Declared
#: here so a typo in the YAML is a load-time warning rather than a requirement
#: that silently never applies.
KNOWN_CONDITIONS: FrozenSet[str] = frozenset(
    {
        "material_product_movement",
        "comparable_survey_data",
        "comparable_years_available",
        "quarterly_data_available",
        "whitespace_enabled",
    }
)


@dataclass(frozen=True)
class Requirement:
    """One kind of evidence an answer can be required to carry."""

    key: str
    label: str
    source: str
    evidence: str
    limitation: str

    def unmet(self, detail: str = "") -> "UnmetRequirement":
        """This requirement as a publishable limitation."""
        return UnmetRequirement(self, detail)


@dataclass(frozen=True)
class UnmetRequirement:
    """A requirement the turn could not satisfy, and why.

    `detail` is the specific reason for THIS scope when one is known ("2024 stops
    at Q2"); the requirement's generic sentence is the fallback. A limitation
    that says which scope defeated it is actionable; one that says "no data" is
    not.
    """

    requirement: Requirement
    detail: str = ""

    @property
    def text(self) -> str:
        return self.detail or self.requirement.limitation


@dataclass(frozen=True)
class IntentSpec:
    """The evidence contract for one analytical intent."""

    key: str
    aliases: Tuple[str, ...]
    required: Tuple[str, ...]
    conditional: Mapping[str, str]


@dataclass(frozen=True)
class Policy:
    """Product decisions that the data cannot settle.

    These are defaults, not rules: an explicit instruction in the question
    ("premium only") overrides `performance_sources`, and the caller applies that
    override rather than this object knowing about user text.
    """

    performance_sources: Tuple[str, ...] = (GPR,)
    survey_requires_comparable_data: bool = True
    whitespace_in_performance: bool = False

    def conditions(self) -> FrozenSet[str]:
        """Conditions this policy alone satisfies, before any data is seen."""
        satisfied = set()
        if self.whitespace_in_performance:
            satisfied.add("whitespace_enabled")
        return frozenset(satisfied)


@dataclass(frozen=True)
class EvidenceContract:
    """What this turn must produce: the selected requirements, in order.

    `selected` is what the planner must gather. `deferred` is what the intent
    declares but this turn's conditions excluded — kept so the answer can say
    "no product moved materially enough to look at industries" instead of
    silently skipping the drill-down.
    """

    intent: str
    selected: Tuple[Requirement, ...] = ()
    deferred: Tuple[Requirement, ...] = ()

    def keys(self) -> Tuple[str, ...]:
        return tuple(r.key for r in self.selected)

    def sources(self) -> Tuple[str, ...]:
        """Datasets the selected requirements need, in declaration order."""
        return tuple(dict.fromkeys(r.source for r in self.selected))

    def requires(self, key: str) -> bool:
        return any(r.key == key for r in self.selected)


# --------------------------------------------------------------------------- #
# Library
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RequirementLibrary:
    """Parsed `intents.yaml`: requirements, intents and policy."""

    requirements: Mapping[str, Requirement] = field(default_factory=dict)
    intents: Mapping[str, IntentSpec] = field(default_factory=dict)
    policy: Policy = field(default_factory=Policy)

    def requirement(self, key: str) -> Optional[Requirement]:
        return self.requirements.get(key)

    def intent(self, key: str) -> Optional[IntentSpec]:
        """An intent by key or alias, case-insensitively."""
        needle = (key or "").strip().lower()
        if needle in self.intents:
            return self.intents[needle]
        for spec in self.intents.values():
            if needle in (alias.lower() for alias in spec.aliases):
                return spec
        return None

    def names(self) -> Tuple[str, ...]:
        return tuple(self.intents)


def parse_requirement(key: str, raw: Mapping[str, Any]) -> Requirement:
    source = str(raw.get("source", GPR)).strip().lower()
    if source not in {GPR, SURVEY}:
        logger.warning("requirement %s declares unknown source %r", key, source)
    return Requirement(
        key=key,
        label=_text(raw.get("label")) or key.replace("_", " ").capitalize(),
        source=source,
        evidence=_text(raw.get("evidence")),
        limitation=_text(raw.get("limitation")),
    )


def parse_intent(key: str, raw: Mapping[str, Any], known: Iterable[str]) -> IntentSpec:
    known = set(known)
    required = tuple(str(r) for r in (raw.get("required") or []) if str(r) in known)
    conditional = {
        str(name): str(condition)
        for name, condition in (raw.get("conditional") or {}).items()
        if str(name) in known
    }
    for name, condition in conditional.items():
        if condition not in KNOWN_CONDITIONS:
            logger.warning(
                "intent %s gates %s on unknown condition %r; it will never apply",
                key, name, condition,
            )
    return IntentSpec(
        key=key,
        aliases=tuple(str(a) for a in (raw.get("aliases") or [])),
        required=required,
        conditional=conditional,
    )


def parse_policy(raw: Mapping[str, Any]) -> Policy:
    sources = tuple(
        str(s).strip().lower()
        for s in (raw.get("performance_sources") or [GPR])
        if str(s).strip().lower() in {GPR, SURVEY}
    )
    return Policy(
        performance_sources=sources or (GPR,),
        survey_requires_comparable_data=bool(
            raw.get("survey_requires_comparable_data", True)
        ),
        whitespace_in_performance=bool(raw.get("whitespace_in_performance", False)),
    )


def load_library(path: Path = _INTENTS_PATH) -> RequirementLibrary:
    """Parse `intents.yaml`. A missing or broken file yields an empty library."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:  # noqa: BLE001 - config must not crash a turn
        logger.error("could not load %s: %s", path, exc)
        return RequirementLibrary()
    requirements = {
        key: parse_requirement(key, value or {})
        for key, value in (raw.get("requirements") or {}).items()
    }
    intents = {
        key: parse_intent(key, value or {}, requirements)
        for key, value in (raw.get("intents") or {}).items()
    }
    return RequirementLibrary(requirements, intents, parse_policy(raw.get("policy") or {}))


_library: Optional[RequirementLibrary] = None


def get_requirements() -> RequirementLibrary:
    """Process-wide singleton, parsed on first use."""
    global _library
    if _library is None:
        _library = load_library()
    return _library


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


def build_contract(
    intent: str,
    *,
    conditions: Iterable[str] = (),
    allowed_sources: Iterable[str] = (),
    library: Optional[RequirementLibrary] = None,
) -> EvidenceContract:
    """The evidence contract for `intent` under this turn's conditions.

    `conditions` are the condition names the turn has established (data exists,
    a product moved materially, whitespace is enabled). `allowed_sources` narrows
    the contract to the datasets this turn may draw on — that is where an explicit
    "premium only" lands, and where the survey half drops out when policy or the
    router excluded it. An empty `allowed_sources` means no restriction.
    """
    library = library or get_requirements()
    spec = library.intent(intent)
    if spec is None:
        return EvidenceContract(intent=intent)

    satisfied = set(conditions)
    permitted = {s.strip().lower() for s in allowed_sources if str(s).strip()}

    selected, deferred = [], []
    for key in spec.required:
        requirement = library.requirement(key)
        if requirement is None:
            continue
        (selected if _permits(permitted, requirement) else deferred).append(requirement)
    for key, condition in spec.conditional.items():
        requirement = library.requirement(key)
        if requirement is None:
            continue
        admitted = condition in satisfied and _permits(permitted, requirement)
        (selected if admitted else deferred).append(requirement)

    return EvidenceContract(spec.key, tuple(selected), tuple(deferred))


def _permits(permitted: FrozenSet[str] | set, requirement: Requirement) -> bool:
    return not permitted or requirement.source in permitted


def performance_sources(
    *,
    requested: Iterable[str] = (),
    library: Optional[RequirementLibrary] = None,
) -> Tuple[str, ...]:
    """Datasets a performance question draws on.

    An explicit request wins outright — that is what "explicit user restrictions
    override defaults" means, and it is the only reason this is a function rather
    than a constant. With nothing requested, the configured default applies.
    """
    library = library or get_requirements()
    explicit = tuple(
        s.strip().lower() for s in requested if str(s).strip().lower() in {GPR, SURVEY}
    )
    return explicit or library.policy.performance_sources


def _text(value: Any) -> str:
    """YAML folded scalars keep a trailing newline; nothing downstream wants it."""
    return " ".join(str(value or "").split())
