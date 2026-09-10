"""Typed evidence for chat. No model, database or presentation framework.

Values retain their metric, unit, scope and source throughout the answer. Numeric
matching alone is deliberately not a substitute for this identity.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


PERIOD_COLUMNS = {"year", "quarter", "month", "date", "period", "year_quarter", "yearmonth", "yearquarter"}
DIMENSION_COLUMNS = PERIOD_COLUMNS | {
    "rank_label", "sic_major_class", "sic_minor_class", "client_id", "carrier_id",
    "country_id", "code", "id", "yearmonth", "yearquarter",
}


@dataclass(frozen=True)
class AnswerFact:
    id: str
    metric: str
    value: float
    unit: str
    rendered: str
    dimensions: tuple[tuple[str, str], ...]
    source_id: str
    lens: str
    formula: str = ""
    support: tuple[dict, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FactPack:
    facts: tuple[AnswerFact, ...]
    row_count: int
    conflicts: tuple[str, ...] = ()


def stable_id(prefix: str, value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return prefix + hashlib.sha256(payload.encode()).hexdigest()[:16]


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def metric_unit(metric: str, declared: str = "") -> str:
    if declared in {"currency", "percent", "percentage_points", "score", "rank", "count", "ratio"}:
        return declared
    if declared == "%":
        return "percent"
    if declared.lower() == "nps":
        return "score"
    name = metric.lower()
    if "%" in name or any(w in name for w in ("pct", "percent", "share", "growth", "rate", "yoy")):
        return "percent"
    if any(w in name for w in ("premium", "gwp", "revenue", "amount")):
        return "currency"
    if "rank" in name:
        return "rank"
    if "score" in name or "nps" in name:
        return "score"
    return "number"


def format_value(value: float, unit: str) -> str:
    if unit == "currency":
        for scale, suffix in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
            if abs(value) >= scale:
                return f"${value / scale:,.2f}".rstrip("0").rstrip(".") + suffix
        return f"${value:,.2f}".rstrip("0").rstrip(".")
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text + {"percent": "%", "percentage_points": " percentage points"}.get(unit, "")


def label(metric: str) -> str:
    text = re.sub(r"(?i)\bmarket_", "Marsh_book_", metric).replace("_", " ").strip()
    text = re.sub(r"(?i)\bpct\b", "", text).strip()
    text = re.sub(r"(?i)\bpeer avg\b", "peer average", text)
    if "premium" in text.lower() and "marsh" not in text.lower():
        text = "Marsh-placed " + text
    return text[:1].upper() + text[1:]


def row_dimensions(row: Mapping[str, Any], scope: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    dims = {}
    for key, value in scope.items():
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        if value is not None and str(value).strip():
            dims[str(key)] = str(value)
    for key, value in row.items():
        if value is not None and (key.lower() in DIMENSION_COLUMNS or number(value) is None):
            dims[str(key)] = str(value)
    return tuple(sorted(dims.items()))


def facts_for_set(item: Mapping[str, Any]) -> list[AnswerFact]:
    source = stable_id("s_", [item.get("flow"), item.get("sql"), item.get("scope")])
    metadata = item.get("metrics") or {}
    facts = []
    # Prefer the original calculation facts. Flattened chart rows cannot retain
    # separate denominators, formulas and dimensions for each measure.
    for raw in item.get("facts") or []:
        value = number(raw.get("value"))
        if value is None:
            continue
        metric = str(raw.get("column") or raw.get("name") or "Value")
        dims = row_dimensions(raw.get("dims") or {}, item.get("scope") or {})
        # Numeric dimension values remain dimensions on a typed calculation.
        dims = tuple(sorted(dict(dims, **{str(k): str(v) for k, v in (raw.get("dims") or {}).items() if v is not None}).items()))
        unit = metric_unit(metric, raw.get("unit") or "")
        identity = [source, dims, metric, value, unit]
        facts.append(AnswerFact(stable_id("f_", identity), metric, value, unit,
                                format_value(value, unit), dims, source,
                                str(item.get("lens") or item.get("flow") or ""),
                                str(raw.get("formula") or "Recorded tool calculation"),
                                tuple(raw.get("support") or [])))
    if item.get("facts"):
        return facts
    for row in item.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        dims = row_dimensions(row, item.get("scope") or {})
        for metric, raw in row.items():
            value = number(raw)
            if value is None or metric.lower() in DIMENSION_COLUMNS:
                continue
            info = metadata.get(metric) or {}
            unit = metric_unit(metric, info.get("unit", ""))
            identity = [source, dims, metric, value, unit]
            facts.append(AnswerFact(
                stable_id("f_", identity), metric, value, unit, format_value(value, unit),
                dims, source, str(item.get("lens") or item.get("flow") or ""),
                str(info.get("formula") or "Value returned by the recorded calculation"),
            ))
    return facts


def build_fact_pack(evidence: Sequence[Mapping[str, Any]]) -> FactPack:
    """Collect every result set in deterministic order, retaining conflicting facts."""
    unique = {}
    for item in evidence:
        for fact in facts_for_set(item):
            unique[fact.id] = fact
    facts = tuple(sorted(unique.values(), key=lambda f: (f.dimensions, f.metric, f.source_id)))
    by_identity: dict[tuple, set[float]] = {}
    for fact in facts:
        key = (fact.metric, fact.unit, fact.dimensions)
        by_identity.setdefault(key, set()).add(fact.value)
    conflicts = tuple(stable_id("conflict_", key) for key, values in by_identity.items() if len(values) > 1)
    return FactPack(facts, sum(len(e.get("rows") or []) for e in evidence), conflicts)
