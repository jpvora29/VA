"""Peer confidentiality, enforced in code rather than asked for in a prompt.

The rule is a business one and it is absolute: a carrier-facing answer may
describe peers only in aggregate. It may name the subject the question is about,
and it may name Marsh (whose book is the market proxy). It may never name an
individual peer.

Until now that rule existed only as English, in two system prompts
(``analyst.common._CONFIDENTIALITY`` and ``insight_writer._OUTPUT_CONTRACT``). A
prompt is a request, so peer names appeared whenever a model felt like quoting a
row -- and the two surfaces that never see a prompt at all, the data table under
a chart and the chart's own axis labels, had no protection whatsoever.

**Where this is enforced.** At the evidence boundary, not at the output. A solver
still receives real peer names from its tools, because it needs them to write the
next query (``WHERE Carrier_Group IN (...)``). What gets *recorded as evidence*
is redacted. Evidence is the sole input to the insight-writer, the shown table
and the chart picker, so closing that one boundary closes all three surfaces at
once -- including the token stream, which no post-hoc scrub of the final text
could have caught in time.

**What redaction does.** It replaces an individual peer's identity with a stable
anonymous label ("Peer 1", "Peer 2"), keeping the row and its numbers intact.
Aggregating instead would mean inventing arithmetic over measures whose
aggregation this layer cannot know; anonymising keeps every figure exactly as the
database returned it while making the row non-identifying. Labels are assigned in
first-appearance order and shared across one solver's evidence, so a peer reads
consistently within an answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

# Marsh's book IS the market proxy, not a peer -- the domain rules name it freely.
ALWAYS_NAMEABLE: FrozenSet[str] = frozenset({"marsh"})

# Column names that hold a carrier identity. The flow registry gives the
# authoritative ones (Carrier_Group, Overall_Peer_Group, ...); this catches the
# aliases a solver invents in hand-written SQL -- "AS peer", "AS peer_name",
# "AS competitor".
_IDENTITY_COLUMN_RE = re.compile(
    r"(?i)\b(carrier|peer|competitor|insurer|market_?participant)"
)

_LABEL = "Peer {n}"

# What an unrecognised peer mention in prose becomes when we have no label for it.
_UNLABELLED = "a peer"


def _norm(value: Any) -> str:
    """Comparison form of a carrier name: case- and whitespace-insensitive."""
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _is_name(value: Any) -> bool:
    """True when `value` could be a carrier's name — i.e. it is text.

    The column regex deliberately matches loosely so a solver's invented alias
    ("AS competitor") is still caught, and that makes it match measure columns
    too: `compute_peer_average_total` returns `peer_average` and `peers`, which
    hold a figure and a COUNT. Without this guard the peer benchmark's own number
    would be replaced by a label — destroying the very value the comparison
    exists to report. An identity is text; a measure is not.
    """
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return False
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        float(value)
    except ValueError:
        return True
    return False


@dataclass(frozen=True)
class PeerPolicy:
    """Who may be named in one turn's output, and where identities can hide.

    ``subjects`` are the names an answer may use verbatim: the carrier the
    question is about, plus ``ALWAYS_NAMEABLE``. Anything else found in an
    identity column is a peer.
    """

    identity_columns: FrozenSet[str] = frozenset()
    subjects: FrozenSet[str] = frozenset(ALWAYS_NAMEABLE)

    def is_identity_column(self, column: Any) -> bool:
        name = str(column or "")
        return name in self.identity_columns or bool(_IDENTITY_COLUMN_RE.search(name))

    def may_name(self, value: Any) -> bool:
        return _norm(value) in self.subjects


def registry_identity_columns(flow: str) -> FrozenSet[str]:
    """The flow's declared carrier + peer-membership columns.

    Registry-driven, so a schema change moves this with it. A flow the registry
    does not know contributes nothing and the regex above still covers it.
    """
    try:
        from core.analytics.sql import flow_spec  # lazy: keeps this module light

        spec = flow_spec(flow)
    except Exception:  # noqa: BLE001 - an unknown flow falls back to the regex
        return frozenset()
    columns = {spec.entity_columns.get("carrier")}
    peers = spec.peer_columns or {}
    columns.update({peers.get("key"), peers.get("members")})
    return frozenset(c for c in columns if c)


def build_policy(flow: str, subjects: Iterable[Any] = ()) -> PeerPolicy:
    """The naming policy for one turn on ``flow``, given the question's subject(s)."""
    named = {_norm(s) for s in subjects if _norm(s)}
    return PeerPolicy(
        identity_columns=registry_identity_columns(flow),
        subjects=frozenset(named | ALWAYS_NAMEABLE),
    )


def subjects_from_resolved(
    resolved: Optional[Dict[str, Any]], flow: str
) -> Tuple[str, ...]:
    """The carriers this turn is ABOUT, read off the grounded schema slice.

    The schema-identifier has already matched the user's wording to exact stored
    values, so whatever it resolved under an identity column is the question's
    subject -- two of them for a head-to-head comparison, which is why this
    returns every match rather than one. Everything else stays a peer.
    """
    probe = PeerPolicy(identity_columns=registry_identity_columns(flow))
    named: List[str] = []
    for column, values in (resolved or {}).items():
        if not probe.is_identity_column(column):
            continue
        named.extend(str(v) for v in (values or []) if str(v).strip())
    return tuple(named)


def redactor_for(
    flow: str,
    resolved: Optional[Dict[str, Any]] = None,
    custom_peers: Optional[Dict[str, Any]] = None,
) -> "PeerRedactor":
    """The redactor for one turn on ``flow`` -- the factory every caller uses.

    ``resolved`` is the turn's already-grounded filters (the analyst's
    ``SchemaSlice.resolved_values``, or the rails' ``resolved_filters_of``); the
    carriers in it are the question's subjects. A pinned custom peer set names its
    subject explicitly, so that is honoured too.
    """
    subjects = [
        *subjects_from_resolved(resolved, flow),
        (custom_peers or {}).get("carrier") or "",
    ]
    return PeerRedactor(build_policy(flow, subjects))


def redacted_names(evidence: Iterable[Any]) -> Tuple[str, ...]:
    """Every peer name hidden anywhere in one turn's evidence, de-duplicated.

    Each solver stamps its own hidden vocabulary onto the items it produced; the
    union is what the final prose is scrubbed against.
    """
    seen: Dict[str, str] = {}
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        for name in item.get("redacted_peers") or ():
            seen.setdefault(_norm(name), str(name))
    return tuple(seen.values())


def redact_text(
    text: str,
    names: Iterable[str],
    policy: PeerPolicy,
    aliases: Optional[Dict[str, str]] = None,
) -> str:
    """Replace each peer name in ``text`` with its label (or "a peer").

    Subject names are matched too, and map to themselves. That is what stops a
    peer name which is a SUBSTRING of the subject from corrupting it: with both in
    one longest-first alternation, "AXA XL" matches before "AXA" can bite into it.
    """
    wanted = [str(n) for n in names if str(n or "").strip()]
    if not text or not wanted:
        return text or ""

    aliases = aliases or {}
    keep = {n for n in policy.subjects if n}
    # Both peers and subjects go into one alternation; subjects map to themselves.
    candidates = {_norm(n): n for n in wanted}
    candidates.update({_norm(n): n for n in keep})
    ordered = sorted(candidates.values(), key=lambda n: (-len(n), n.lower()))
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(n) for n in ordered) + r")(?!\w)",
        re.IGNORECASE,
    )

    def _swap(match: "re.Match[str]") -> str:
        key = _norm(match.group(0))
        if key in policy.subjects:
            return match.group(0)
        return aliases.get(key, _UNLABELLED)

    return pattern.sub(_swap, text)


@dataclass
class PeerRedactor:
    """Applies a ``PeerPolicy`` to rows and to text, remembering what it hid.

    One redactor is built per solver and shared across its tool calls, so the same
    peer keeps the same label everywhere in one answer. ``redacted`` is the exact
    vocabulary that was removed -- precise enough to scrub the final prose without
    needing a global list of every carrier in the market.
    """

    policy: PeerPolicy
    _aliases: Dict[str, str] = field(default_factory=dict)
    _originals: Dict[str, str] = field(default_factory=dict)

    @property
    def redacted(self) -> Tuple[str, ...]:
        """The peer names this redactor has hidden, in the order it met them."""
        return tuple(self._originals.values())

    def _alias(self, value: Any) -> str:
        key = _norm(value)
        alias = self._aliases.get(key)
        if alias is None:
            alias = _LABEL.format(n=len(self._aliases) + 1)
            self._aliases[key] = alias
            self._originals[key] = str(value)
        return alias

    def _redact_cell(self, column: Any, value: Any) -> Any:
        if not _is_name(value) or not self.policy.is_identity_column(column):
            return value
        if self.policy.may_name(value):
            return value
        return self._alias(value)

    def rows(self, rows: Sequence[Any]) -> List[Any]:
        """Copy of ``rows`` with every individual peer identity replaced by a label.

        Non-dict rows and non-identity columns pass through untouched, so a
        computed peer average -- which carries a peer COUNT and no name -- comes
        out exactly as the primitive produced it.
        """
        out: List[Any] = []
        for row in rows or []:
            if not isinstance(row, dict):
                out.append(row)
                continue
            out.append({c: self._redact_cell(c, v) for c, v in row.items()})
        return out

    def text(self, text: str) -> str:
        """Replace any hidden peer's name in ``text`` with its label.

        Defence in depth: with evidence redacted the writer never sees these
        names, so this should find nothing. It covers the path where a name
        reaches the prose another way -- the user's own question, a schema note.
        """
        return redact_text(text, self._originals.values(), self.policy, self._aliases)
