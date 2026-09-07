"""The analytical scope of a turn, as named chips.

"Preserve scope everywhere" is a product-wide principle: the user should always
be able to see which carrier, country, product, industry, period and peer set an
answer was built from — above the chat composer, on the Boardroom, and on the
exported slide.

Those three surfaces must agree, so the derivation lives here, once, as pure
functions over the turn's `RoutingContext`. The UI renders :class:`ScopeChip`s;
:func:`scope_line` renders the same chips as the single line PowerPoint uses.

Scope is *derived*, never invented: a chip appears only when the turn actually
resolved that filter (or explicitly inherited it from an earlier turn, which the
chip says).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# How a chip got its value. Shown as the chip's tooltip so an inherited filter is
# never mistaken for one the user just typed.
ASKED = "asked in this question"
INHERITED = "carried over from an earlier question"
CUSTOM = "hand-picked peer set"

# Chip kinds, in the order the roadmap prints them, with the column-name shape
# that feeds each one. Order is display order; the regex is matched against the
# resolved filter's column name.
CHIP_RULES: Tuple[Tuple[str, str, str, "re.Pattern[str]"], ...] = (
    ("country", "Country", "bi bi-globe2", re.compile(r"(?i)country|market|region")),
    ("product", "Product", "bi bi-box-seam", re.compile(r"(?i)product|line_of_business|\blob\b|cover")),
    ("industry", "Industry", "bi bi-buildings", re.compile(r"(?i)industry|sector|sic")),
    ("segment", "Segment", "bi bi-diagram-3", re.compile(r"(?i)segment|size|band")),
    ("period", "Period", "bi bi-calendar3", re.compile(r"(?i)year|quarter|month|period|date")),
    ("carrier", "Carrier", "bi bi-shield-check", re.compile(r"(?i)carrier|insurer|group")),
)

_CHIP_BY_KEY = {key: (label, icon) for key, label, icon, _rx in CHIP_RULES}

# How many values a chip prints before it collapses to "+N more".
_MAX_VALUES = 2


@dataclass(frozen=True)
class ScopeChip:
    """One named piece of the current analytical scope."""

    key: str
    label: str
    value: str
    icon: str
    source: str = ASKED

    def as_dict(self) -> Dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "icon": self.icon,
            "source": self.source,
        }


def chip_from_dict(raw: Mapping[str, Any]) -> ScopeChip:
    """Rebuild a chip from its stored form (the UI keeps scope in a dcc.Store)."""
    key = str(raw.get("key") or "")
    label, icon = _CHIP_BY_KEY.get(key, (str(raw.get("label") or key.title()), "bi bi-funnel"))
    return ScopeChip(
        key=key,
        label=str(raw.get("label") or label),
        value=str(raw.get("value") or ""),
        icon=str(raw.get("icon") or icon),
        source=str(raw.get("source") or ASKED),
    )


# ───────────────────────────── derivation ──────────────────────────────


def chips_from_state(
    state: Mapping[str, Any], custom_peers: Optional[Mapping[str, Any]] = None
) -> List[ScopeChip]:
    """The scope of one finished turn, read from its routing context.

    Reads, in order of authority: the deterministically resolved filters, the
    entity mentions the context filler extracted, the inherited filters, and the
    timeframe hint. Custom peers come from the UI, not the graph, so they are
    passed in.
    """
    context = _as_mapping(state.get("routing_context"))
    resolved = _as_mapping(context.get("resolved_filters"))
    entities = _as_mapping(context.get("entities"))
    inherited = _inherited_values(context)

    values: Dict[str, List[str]] = {}
    sources: Dict[str, str] = {}
    for column, raw in resolved.items():
        key = _key_for_column(str(column))
        if not key:
            continue
        for value in _clean_values(raw):
            _add(values, sources, key, value, ASKED)

    # Resolved filters are canonical; a verbatim mention only fills a chip they
    # left empty (otherwise "Zurich" would print beside "ZURICH GROUP"). Same for
    # inherited values, which are the weakest claim on a chip.
    resolved_keys = set(values)
    for key, value in _entity_values(entities):
        if key not in resolved_keys:
            _add(values, sources, key, value, ASKED)

    mentioned_keys = set(values)
    for key, value in inherited:
        if key not in mentioned_keys:
            _add(values, sources, key, value, INHERITED)

    period = _period_value(context)
    if period and "period" not in values:
        _add(values, sources, "period", period, _period_source(context))

    chips = [
        ScopeChip(
            key=key,
            label=_CHIP_BY_KEY[key][0],
            value=_join(values[key]),
            icon=_CHIP_BY_KEY[key][1],
            source=sources[key],
        )
        for key, _label, _icon, _rx in CHIP_RULES
        if values.get(key)
    ]
    peers = peers_chip(custom_peers)
    if peers is not None:
        chips.append(peers)
    return chips


def peers_chip(custom_peers: Optional[Mapping[str, Any]]) -> Optional[ScopeChip]:
    """The peer-set chip — present only while a hand-picked set is pinned."""
    custom_peers = custom_peers or {}
    peers = custom_peers.get("peers") or []
    carrier = str(custom_peers.get("carrier") or "").strip()
    if not peers or not carrier:
        return None
    return ScopeChip(
        key="peers",
        label="Peers",
        value=f"Custom peers ({len(peers)})",
        icon="bi bi-people",
        source=CUSTOM,
    )


def chips_to_dicts(chips: Iterable[ScopeChip]) -> List[Dict[str, str]]:
    return [chip.as_dict() for chip in chips]


def chips_from_dicts(raw: Optional[Sequence[Mapping[str, Any]]]) -> List[ScopeChip]:
    return [chip_from_dict(item) for item in (raw or []) if isinstance(item, Mapping)]


def scope_line(chips: Iterable[ScopeChip]) -> str:
    """The one-line scope PowerPoint prints, so the slide matches the screen."""
    return " | ".join(f"{chip.label}: {chip.value}" for chip in chips)


# ───────────────────────────── helpers ──────────────────────────────


def _add(
    values: Dict[str, List[str]],
    sources: Dict[str, str],
    key: str,
    value: str,
    source: str,
) -> None:
    """Record one value for a chip, keeping the first source that claimed it."""
    bucket = values.setdefault(key, [])
    if value and not any(value.lower() == existing.lower() for existing in bucket):
        bucket.append(value)
    sources.setdefault(key, source)


def _key_for_column(column: str) -> str:
    for key, _label, _icon, pattern in CHIP_RULES:
        if pattern.search(column):
            return key
    return ""


def _entity_values(entities: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Entity mentions, mapped onto chip keys."""
    pairs: List[Tuple[str, str]] = []
    for field, key in (
        ("countries", "country"),
        ("products", "product"),
        ("industries", "industry"),
        ("segments", "segment"),
        ("years", "period"),
        ("carriers", "carrier"),
    ):
        for value in _clean_values(entities.get(field)):
            pairs.append((key, value))
    return pairs


def _inherited_values(context: Mapping[str, Any]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for field, key in (
        ("inherited_country", "country"),
        ("inherited_carrier", "carrier"),
        ("inherited_year", "period"),
    ):
        value = str(context.get(field) or "").strip()
        if value:
            pairs.append((key, value))
    return pairs


def _period_value(context: Mapping[str, Any]) -> str:
    """A readable period when no year filter resolved — the timeframe hint."""
    hint = str(context.get("timeframe_hint") or "").strip()
    if hint and len(hint) <= 40 and "(" not in hint:
        return hint
    return str(context.get("inherited_year") or "").strip()


def _period_source(context: Mapping[str, Any]) -> str:
    return ASKED if str(context.get("timeframe_hint") or "").strip() else INHERITED


def _clean_values(raw: Any) -> List[str]:
    if raw is None or isinstance(raw, (dict, Mapping)):
        return []
    if isinstance(raw, (str, int, float)):
        raw = [raw]
    return [str(v).strip() for v in raw if str(v).strip()]


def _join(values: Sequence[str]) -> str:
    shown = list(values)[:_MAX_VALUES]
    extra = len(values) - len(shown)
    text = ", ".join(shown)
    return f"{text} +{extra} more" if extra > 0 else text


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Accept a pydantic model, a dict, or nothing at all."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:  # noqa: BLE001 - scope must never break a turn
            return {}
    return {}
