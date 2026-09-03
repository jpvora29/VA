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
    always_include_current_and_prior: bool = True
    require_absolute_change: bool = True
    suppress_if_current_premium_below: float = 1_000_000.0


@dataclass(frozen=True)
class MaterialityRules:
    min_premium_for_industry_commentary: float = 5_000_000.0
    min_premium_for_practice_commentary: float = 5_000_000.0
    min_share_of_portfolio_pct: float = 3.0


@dataclass(frozen=True)
class DriverRules:
    require_driver_for_large_change: bool = True
    large_change_pct: float = 20.0
    min_driver_contribution_pct: float = 40.0


@dataclass(frozen=True)
class CommentaryRules:
    max_bullets_per_slide: int = 3
    max_sentences_per_bullet: int = 2
    block_named_peer_mentions: bool = True
    block_causal_language_without_driver_fact: bool = True
    min_binding_confidence: float = 0.5


@dataclass(frozen=True)
class RankRules:
    window: int = 5


@dataclass(frozen=True)
class WhitespaceRules:
    material_market_gwp: float = 5_000_000.0
    carrier_ceiling: float = 0.0
    top_n: int = 5


@dataclass(frozen=True)
class SegmentRules:
    """What makes one industry / client-segment row worth a commentary sentence.

    ``dims`` is the decomposition allowlist, so adding a dimension is a config change
    rather than a code change. ``min_carriers`` is a CONFIDENTIALITY floor, not a
    statistical one: with two carriers in a segment a "top-5 peer average" is one peer's
    number, which ``peer.aggregate_only`` forbids.
    """

    dims: Tuple[str, ...] = ("SIC_Major_Class", "Client_Segment")
    min_carriers: int = 3
    thin_share_margin: float = 2.0
    behind_peer_margin: float = 1.0
    strong_share_margin: float = 2.0
    losing_share_move: float = 1.0
    deviation_pp: float = 1.5
    max_findings_per_column: int = 2


@dataclass(frozen=True)
class OpportunityRules:
    top_n: int = 5


@dataclass(frozen=True)
class TemporalRules:
    ttm_min_months: int = 12
    mom_significant_pct: float = 5.0
    qoq_significant_pct: float = 8.0


@dataclass(frozen=True)
class RulesConfig:
    truncation: TruncationRules = field(default_factory=TruncationRules)
    yoy: YoyRules = field(default_factory=YoyRules)
    rank: RankRules = field(default_factory=RankRules)
    whitespace: WhitespaceRules = field(default_factory=WhitespaceRules)
    opportunity: OpportunityRules = field(default_factory=OpportunityRules)
    segments: SegmentRules = field(default_factory=SegmentRules)
    temporal: TemporalRules = field(default_factory=TemporalRules)
    materiality: MaterialityRules = field(default_factory=MaterialityRules)
    drivers: DriverRules = field(default_factory=DriverRules)
    commentary: CommentaryRules = field(default_factory=CommentaryRules)
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


def _strs(d: Dict[str, Any], key: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    """A list-of-strings setting. A malformed or empty list falls back to the default —
    an empty decomposition allowlist would silently turn every segment finding off."""
    val = d.get(key)
    if not isinstance(val, (list, tuple)):
        return default
    out = tuple(str(v).strip() for v in val if str(v).strip())
    return out or default


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
    opp = _section(meta, "opportunity")
    seg = _section(meta, "segments")
    temporal = _section(meta, "temporal")
    mat = _section(meta, "materiality")
    drv = _section(meta, "drivers")
    comm = _section(meta, "commentary")
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
            always_include_current_and_prior=bool(yoy.get("always_include_current_and_prior", True)),
            require_absolute_change=bool(yoy.get("require_absolute_change", True)),
            suppress_if_current_premium_below=_num(yoy, "suppress_if_current_premium_below", 1_000_000.0),
        ),
        rank=RankRules(window=_int(rank, "window", 5)),
        whitespace=WhitespaceRules(
            material_market_gwp=_num(ws, "material_market_gwp", 5_000_000.0),
            carrier_ceiling=_num(ws, "carrier_ceiling", 0.0),
            top_n=_int(ws, "top_n", 5),
        ),
        opportunity=OpportunityRules(top_n=_int(opp, "top_n", 5)),
        segments=SegmentRules(
            dims=_strs(seg, "dims", ("SIC_Major_Class", "Client_Segment")),
            min_carriers=_int(seg, "min_carriers", 3),
            thin_share_margin=_num(seg, "thin_share_margin", 2.0),
            behind_peer_margin=_num(seg, "behind_peer_margin", 1.0),
            strong_share_margin=_num(seg, "strong_share_margin", 2.0),
            losing_share_move=_num(seg, "losing_share_move", 1.0),
            deviation_pp=_num(seg, "deviation_pp", 1.5),
            max_findings_per_column=_int(seg, "max_findings_per_column", 2),
        ),
        temporal=TemporalRules(
            ttm_min_months=_int(temporal, "ttm_min_months", 12),
            mom_significant_pct=_num(temporal, "mom_significant_pct", 5.0),
            qoq_significant_pct=_num(temporal, "qoq_significant_pct", 8.0),
        ),
        materiality=MaterialityRules(
            min_premium_for_industry_commentary=_num(mat, "min_premium_for_industry_commentary", 5_000_000.0),
            min_premium_for_practice_commentary=_num(mat, "min_premium_for_practice_commentary", 5_000_000.0),
            min_share_of_portfolio_pct=_num(mat, "min_share_of_portfolio_pct", 3.0),
        ),
        drivers=DriverRules(
            require_driver_for_large_change=bool(drv.get("require_driver_for_large_change", True)),
            large_change_pct=_num(drv, "large_change_pct", 20.0),
            min_driver_contribution_pct=_num(drv, "min_driver_contribution_pct", 40.0),
        ),
        commentary=CommentaryRules(
            max_bullets_per_slide=_int(comm, "max_bullets_per_slide", 3),
            max_sentences_per_bullet=_int(comm, "max_sentences_per_bullet", 2),
            block_named_peer_mentions=bool(comm.get("block_named_peer_mentions", True)),
            block_causal_language_without_driver_fact=bool(
                comm.get("block_causal_language_without_driver_fact", True)
            ),
            min_binding_confidence=_num(comm, "min_binding_confidence", 0.5),
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
