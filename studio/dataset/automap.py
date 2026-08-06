"""Propose what each uploaded column IS — the seed the mapping step opens with.

The HITL step used to open with every dropdown empty, so a 30-column upload was 30
manual decisions before anything could be built. This module makes the first pass and
the user corrects it: every proposal carries WHY it was made (``source``) and how sure
we are (``confidence``), and the row's select box overrides any of it.

Deterministic and explainable — no LLM. The flow registry's own column names and
aliases are the whole vocabulary, so the proposals track the schema rather than a
list maintained here.

Four matchers, best-first, per uploaded column:

    exact   the normalised name IS the canonical column   ("carrier group" -> Carrier_Group)
    alias   the name is one of its declared aliases       ("insurer"       -> Carrier_Group)
    values  the values themselves say what it is          (2019…2026       -> Year)
    token   a qualified name carries the canonical word   ("Premium Amount"-> Premium)
    fuzzy   the names are close enough to be the same     ("Prodct_Line"   -> Product_Line)

A canonical target is claimed by at most ONE uploaded column — the most confident one —
so two year-ish columns cannot both land on ``Year``.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Tuple

from studio.dataset.model import ColumnMapping, ColumnProfile, DatasetProfile

FLOW = "gpr"

# The roles a user column may be mapped onto (same set the Data tab offers).
MAPPABLE_ROLES = frozenset({"entity", "temporal", "measure"})

# Column kinds each role can accept. A money measure MUST be numeric; a label may be
# text or a code. Keeps "Region_Code" off ``Premium`` and "Notes" off ``Year``.
_ROLE_KINDS: Dict[str, frozenset] = {
    "measure": frozenset({"number"}),
    "temporal": frozenset({"number", "date"}),
    "entity": frozenset({"text", "number", "date"}),
}

# How close two normalised names must be before one counts as the other. Tuned to accept
# typos and abbreviations ("Prodct_Line" scores 0.95) and reject the near-misses that mean
# something else entirely — "Insurer" against CLIENT_NAME's "insured" scores 0.86, and a
# carrier is not a client.
_FUZZY_FLOOR = 0.88

# Confidence per matcher — the ranking that settles which column claims a target.
_EXACT, _ALIAS, _VALUES = 1.0, 0.95, 0.80

# A numeric column whose values all sit in this range, with few enough distinct ones to
# be a reporting period rather than an amount, is a year.
_YEAR_RANGE = (1990, 2100)
_YEAR_MAX_DISTINCT = 60


@dataclass(frozen=True)
class Target:
    """A canonical column an upload can map onto, plus the words that name it."""

    name: str
    role: str
    definition: str = ""
    vocabulary: Tuple[str, ...] = ()        # normalised name + declared aliases


@dataclass(frozen=True)
class Proposal:
    """One matcher's answer for one uploaded column."""

    column: str
    target: str
    confidence: float
    source: str                             # alias | fuzzy | values
    definition: str = ""


# ── the vocabulary (from the flow registry) ──────────────────────────────────


def _normalise(text: str) -> str:
    """A column name reduced to its letters and digits, lower-cased.

    "Carrier_Group", "carrier group" and "CarrierGroup" are one name; punctuation and
    case are how spreadsheets differ from schemas, not what they mean.
    """
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def canonical_targets(flow: str = FLOW) -> Tuple[Target, ...]:
    """Every canonical column an upload can map onto, in registry order."""
    from core.registry import get_flow_registry

    spec = get_flow_registry().get(flow)
    if spec is None:
        return ()
    return tuple(
        Target(
            name=col.name,
            role=col.role,
            definition=col.definition,
            vocabulary=tuple({_normalise(col.name), *(_normalise(a) for a in col.aliases)}),
        )
        for col in spec.columns.values()
        if col.role in MAPPABLE_ROLES
    )


def _accepts(target: Target, profile: ColumnProfile) -> bool:
    """True when a column of this KIND could plausibly be this target."""
    return profile.kind in _ROLE_KINDS.get(target.role, frozenset())


# ── the matchers ─────────────────────────────────────────────────────────────


def _match_by_name(profile: ColumnProfile, target: Target) -> Optional[Proposal]:
    """Exact or alias match on the column's name."""
    needle = _normalise(profile.name)
    if not needle or needle not in target.vocabulary:
        return None
    confidence = _EXACT if needle == _normalise(target.name) else _ALIAS
    return Proposal(profile.name, target.name, confidence, "alias", target.definition)


def _looks_like_a_year(profile: ColumnProfile) -> bool:
    """True when the sampled values are whole numbers inside the reporting-year range."""
    if profile.kind != "number" or not profile.sample:
        return False
    if profile.n_distinct > _YEAR_MAX_DISTINCT:
        return False
    for raw in profile.sample:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return False
        if not value.is_integer() or not _YEAR_RANGE[0] <= value <= _YEAR_RANGE[1]:
            return False
    return True


def _match_by_values(profile: ColumnProfile, target: Target) -> Optional[Proposal]:
    """What the VALUES say, for the cases a name cannot carry.

    "Yr", "FY" and "Period" share almost no characters with ``Year``, but a numeric
    column holding 2019…2026 can only be one thing.
    """
    if target.name != "Year" or not _looks_like_a_year(profile):
        return None
    return Proposal(profile.name, target.name, _VALUES, "values", target.definition)


def _tokens(name: str) -> Tuple[str, ...]:
    """The words in a column name, lower-cased ("Premium Amount USD" -> prem…, amount, usd)."""
    words, buffer = [], []
    for char in str(name or ""):
        if char.isalnum():
            buffer.append(char.lower())
        elif buffer:
            words.append("".join(buffer))
            buffer = []
    if buffer:
        words.append("".join(buffer))
    return tuple(words)


# A word this short ("id", "no") says nothing on its own, so it never carries a match.
_TOKEN_MIN = 4
# …and the word it does carry must be the SUBSTANCE of the name, not a qualifier on
# something else: "Premium Amount" is a premium, "Client Reference" is not a client.
_TOKEN_SHARE = 0.5
_TOKEN = 0.90


def _match_by_token(profile: ColumnProfile, target: Target) -> Optional[Proposal]:
    """A qualified name — "Premium Amount", "Country Name" — carrying the canonical word."""
    words = _tokens(profile.name)
    total = sum(len(w) for w in words)
    hit = next((w for w in target.vocabulary
                if len(w) >= _TOKEN_MIN and w in words and len(w) >= _TOKEN_SHARE * total), None)
    return None if hit is None else Proposal(
        profile.name, target.name, _TOKEN, "fuzzy", target.definition)


def _match_by_fuzzy(profile: ColumnProfile, target: Target) -> Optional[Proposal]:
    """The closest name in the vocabulary, when it is close enough to be the same word."""
    needle = _normalise(profile.name)
    if not needle:
        return None
    best = max((SequenceMatcher(None, needle, word).ratio() for word in target.vocabulary),
               default=0.0)
    if best < _FUZZY_FLOOR:
        return None
    return Proposal(profile.name, target.name, round(best, 2), "fuzzy", target.definition)


# Order matters: the first matcher to answer for a (column, target) pair wins, and each
# is more certain than the one after it.
_MATCHERS = (_match_by_name, _match_by_values, _match_by_token, _match_by_fuzzy)


def _proposals_for(profile: ColumnProfile, targets: Sequence[Target]) -> List[Proposal]:
    """Every target this one column could be, best first."""
    found = []
    for target in targets:
        if not _accepts(target, profile):
            continue
        for match in _MATCHERS:
            proposal = match(profile, target)
            if proposal is not None:
                found.append(proposal)
                break
    found.sort(key=lambda p: p.confidence, reverse=True)
    return found


def _claim_targets(profiles: Sequence[ColumnProfile],
                   targets: Sequence[Target]) -> Dict[str, Proposal]:
    """``{uploaded column: the proposal it wins}`` — one column per canonical target.

    Settled globally rather than column by column: with "Insurer" and "Carrier Group"
    both in the upload, the exact match takes ``Carrier_Group`` and the alias falls
    through to nothing rather than the first row simply winning by position.
    """
    ranked = sorted(
        (p for profile in profiles for p in _proposals_for(profile, targets)),
        key=lambda p: -p.confidence,
    )
    by_column: Dict[str, Proposal] = {}
    claimed: set = set()
    for proposal in ranked:
        if proposal.column in by_column or proposal.target in claimed:
            continue
        by_column[proposal.column] = proposal
        claimed.add(proposal.target)
    return by_column


# ── the public step ──────────────────────────────────────────────────────────


def propose_mappings(profile: DatasetProfile,
                     *, targets: Optional[Sequence[Target]] = None) -> Tuple[ColumnMapping, ...]:
    """A proposed ``ColumnMapping`` for EVERY uploaded column, in the upload's own order.

    Columns nothing matched come back unmapped — that is a real answer, and the row then
    asks the user for the description that is the only thing explaining such a column.
    """
    columns = profile.columns if profile else ()
    if not columns:
        return ()
    won = _claim_targets(columns, targets if targets is not None else canonical_targets())
    return tuple(
        _as_mapping(column, won.get(column.name)) for column in columns
    )


def _as_mapping(profile: ColumnProfile, proposal: Optional[Proposal]) -> ColumnMapping:
    if proposal is None:
        return ColumnMapping(uploaded=profile.name, source="unmapped")
    return ColumnMapping(
        uploaded=profile.name,
        target=proposal.target,
        description=proposal.definition,
        confidence=proposal.confidence,
        source=proposal.source,
    )


# Mapping ``source`` → how the row explains itself on screen.
SOURCE_LABEL: Dict[str, str] = {
    "alias": "Auto",
    "fuzzy": "Auto · close match",
    "values": "Auto · from values",
    "ai": "AI",
    "user": "You",
    "unmapped": "",
}


def is_proposed(mapping: ColumnMapping) -> bool:
    """True for a mapping the machine proposed and the user has not yet confirmed."""
    return bool(mapping.target) and mapping.source in {"alias", "fuzzy", "values", "ai"}
