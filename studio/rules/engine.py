"""Deterministic rule engine over ``rules.yaml``.

Loads the thresholds once (singleton) and exposes typed accessors + pure rule
functions the renderers and SWOT layer call. Mirrors the resilience of
``document_builder/helpers/design_spec.py``: every value has a hardcoded fallback
equal to the YAML default, and a parse miss returns defaults rather than breaking
a page.

The rules are pure functions of (facts, thresholds) — no DB, no LLM — so they are
trivially unit-testable and explainable in a QBR footnote.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

try:
    import yaml
except ImportError:  # pragma: no cover - falls back to defaults below
    yaml = None

from core.analytics.types import AnalyticsFact

_RULES_PATH = Path(__file__).resolve().parent / "rules.yaml"

T = TypeVar("T")


# ── typed config (defaults == rules.yaml) ───────────────────────────────────


@dataclass(frozen=True)
class TruncationRules:
    trigger_rows: int = 20
    top_n: int = 10
    bottom_n: int = 10


@dataclass(frozen=True)
class YoyRules:
    high_growth_pct: float = 100.0
    significant_premium_floor: float = 1_000_000.0
    always_show_both_years: bool = True


@dataclass(frozen=True)
class RankRules:
    window: int = 5


@dataclass(frozen=True)
class WhitespaceRules:
    material_market_gwp: float = 5_000_000.0
    carrier_ceiling: float = 0.0
    top_n: int = 5


@dataclass(frozen=True)
class RulesConfig:
    truncation: TruncationRules = field(default_factory=TruncationRules)
    yoy: YoyRules = field(default_factory=YoyRules)
    rank: RankRules = field(default_factory=RankRules)
    whitespace: WhitespaceRules = field(default_factory=WhitespaceRules)
    swot: Dict[str, List[str]] = field(default_factory=dict)


# ── loading (singleton, fallback-safe) ──────────────────────────────────────


def _section(meta: Dict[str, Any], key: str) -> Dict[str, Any]:
    val = meta.get(key)
    return val if isinstance(val, dict) else {}


def _num(d: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default


def _int(d: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(d.get(key, default))
    except (TypeError, ValueError):
        return default


def _load() -> RulesConfig:
    if yaml is None:
        return RulesConfig()
    try:
        meta = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - never let a rules parse error break a page
        return RulesConfig()

    trunc = _section(meta, "truncation")
    yoy = _section(meta, "yoy")
    rank = _section(meta, "rank")
    ws = _section(meta, "whitespace")
    swot = meta.get("swot")

    return RulesConfig(
        truncation=TruncationRules(
            trigger_rows=_int(trunc, "trigger_rows", 20),
            top_n=_int(trunc, "top_n", 10),
            bottom_n=_int(trunc, "bottom_n", 10),
        ),
        yoy=YoyRules(
            high_growth_pct=_num(yoy, "high_growth_pct", 100.0),
            significant_premium_floor=_num(yoy, "significant_premium_floor", 1_000_000.0),
            always_show_both_years=bool(yoy.get("always_show_both_years", True)),
        ),
        rank=RankRules(window=_int(rank, "window", 5)),
        whitespace=WhitespaceRules(
            material_market_gwp=_num(ws, "material_market_gwp", 5_000_000.0),
            carrier_ceiling=_num(ws, "carrier_ceiling", 0.0),
            top_n=_int(ws, "top_n", 5),
        ),
        swot=swot if isinstance(swot, dict) else {},
    )


_CONFIG: Optional[RulesConfig] = None


def load_rules() -> RulesConfig:
    """Module-level singleton; parsed once per process."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _load()
    return _CONFIG


# ── pure rule functions ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Truncated:
    """Result of the top/bottom truncation rule."""

    rows: List[Any]
    hidden: int  # number of rows collapsed into the gap (0 => nothing hidden)


def truncate(
    rows: List[T],
    *,
    key: Callable[[T], float],
    cfg: Optional[TruncationRules] = None,
) -> Truncated:
    """If ``rows`` exceeds the trigger, keep the top-N + bottom-N by ``key``.

    'Bottom' means lowest values (not worst rank). Returns the kept rows in
    descending ``key`` order with the hidden count, so the renderer can draw a
    labeled gap row.
    """
    cfg = cfg or load_rules().truncation
    ordered = sorted(rows, key=key, reverse=True)
    if len(ordered) <= cfg.trigger_rows:
        return Truncated(rows=ordered, hidden=0)
    top = ordered[: cfg.top_n]
    bottom = ordered[-cfg.bottom_n :] if cfg.bottom_n else []
    hidden = len(ordered) - len(top) - len(bottom)
    return Truncated(rows=top + bottom, hidden=max(hidden, 0))


def is_significant_yoy(
    growth_pct: float,
    current_premium: float,
    *,
    cfg: Optional[YoyRules] = None,
) -> bool:
    """True when YoY growth clears the high-growth bar AND premium is material."""
    cfg = cfg or load_rules().yoy
    return growth_pct >= cfg.high_growth_pct and current_premium >= cfg.significant_premium_floor


def rank_band(rank: int, *, cfg: Optional[RankRules] = None) -> Tuple[int, int]:
    """The symmetric comparison band [R-window, R+window] (clamped at 1)."""
    cfg = cfg or load_rules().rank
    return (max(1, rank - cfg.window), rank + cfg.window)


def in_rank_band(rank: int, subject_rank: int, *, cfg: Optional[RankRules] = None) -> bool:
    """Whether ``rank`` falls in ``subject_rank``'s band (excluding the subject)."""
    low, high = rank_band(subject_rank, cfg=cfg)
    return low <= rank <= high and rank != subject_rank
