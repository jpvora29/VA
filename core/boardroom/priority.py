"""Watchlist priority — approved rules, never a model's opinion.

The roadmap's first requirement for the Boardroom is that ``High`` must be
defensible: a business user has to see the threshold that was crossed. So the
extractor only ever reports *facts* (premium exposed, movement, how many periods
it has run for), and this module turns those facts into a label plus the list of
rule tests that produced it.

Six tests, in the roadmap's order — materiality, magnitude, early warning,
persistence, business breach, data confidence — each a small pure function
returning a :class:`RuleTest`. :func:`classify` reads as that list.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from logger import get_logger

logger = get_logger(__name__)

_THRESHOLDS_PATH = Path(__file__).parent / "thresholds.yaml"

HIGH = "High"
MEDIUM = "Medium"
LOW = "Low"
UNRATED = "Unrated"


@dataclass(frozen=True)
class Thresholds:
    """The approved numbers behind every priority label."""

    approved: bool = False
    owner: str = ""
    currency: str = "GBP"
    material_premium: float = 5_000_000.0
    material_share_of_wallet_pct: float = 5.0
    watch_move_pct: float = 5.0
    severe_move_pct: float = 10.0
    persistent_periods: int = 2

    def summary(self) -> str:
        """One line naming the numbers, for the "how this was decided" drawer."""
        return (
            f"Material at {_money(self.material_premium, self.currency)} premium "
            f"or {self.material_share_of_wallet_pct:g}% share of wallet; "
            f"watch at {self.watch_move_pct:g}% adverse movement, "
            f"breach at {self.severe_move_pct:g}%; "
            f"persistent after {self.persistent_periods} periods"
        )


@dataclass(frozen=True)
class RuleTest:
    """One approved test and whether this item passed it."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class WatchSignals:
    """The facts a watchlist item carries, normalised for the rule engine."""

    premium_exposed: Optional[float] = None
    share_of_wallet_pct: Optional[float] = None
    movement_pct: Optional[float] = None  # signed; read together with `adverse`
    adverse: bool = True
    consecutive_periods: int = 1
    breached_kpi: str = ""
    periods_comparable: bool = True


@dataclass(frozen=True)
class PriorityVerdict:
    """A label, the sentence that justifies it, and every test behind it."""

    label: str
    reason: str
    tests: Tuple[RuleTest, ...]
    approved: bool
    thresholds: str

    def as_dict(self) -> Dict[str, Any]:
        """JSON-serialisable form for the widget data (which is a plain dict)."""
        return {
            "priority": self.label,
            "priority_reason": self.reason,
            "priority_tests": [
                {"name": t.name, "passed": t.passed, "detail": t.detail} for t in self.tests
            ],
            "priority_approved": self.approved,
            "priority_thresholds": self.thresholds,
        }


# ───────────────────────────── thresholds ──────────────────────────────


@lru_cache(maxsize=1)
def get_thresholds() -> Thresholds:
    """Parse ``thresholds.yaml`` once per process; defaults on any failure."""
    try:
        raw = yaml.safe_load(_THRESHOLDS_PATH.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a bad config must never break a dashboard
        logger.exception("Boardroom: failed to read %s; using defaults", _THRESHOLDS_PATH)
        return Thresholds()
    default = Thresholds()
    return Thresholds(
        approved=bool(raw.get("approved", default.approved)),
        owner=str(raw.get("owner", default.owner) or ""),
        currency=str(raw.get("currency", default.currency) or default.currency),
        material_premium=_number(raw.get("material_premium"), default.material_premium),
        material_share_of_wallet_pct=_number(
            raw.get("material_share_of_wallet_pct"), default.material_share_of_wallet_pct
        ),
        watch_move_pct=_number(raw.get("watch_move_pct"), default.watch_move_pct),
        severe_move_pct=_number(raw.get("severe_move_pct"), default.severe_move_pct),
        persistent_periods=int(
            _number(raw.get("persistent_periods"), default.persistent_periods)
        ),
    )


# ───────────────────────────── the tests ──────────────────────────────


def test_materiality(signals: WatchSignals, t: Thresholds) -> RuleTest:
    """Is the exposure big enough to be worth a board's attention?"""
    premium = signals.premium_exposed
    sow = signals.share_of_wallet_pct
    if premium is None and sow is None:
        return RuleTest("Materiality", False, "No premium or share of wallet reported")
    if premium is not None and premium >= t.material_premium:
        return RuleTest(
            "Materiality",
            True,
            f"{_money(premium, t.currency)} exposed, at or above the "
            f"{_money(t.material_premium, t.currency)} threshold",
        )
    if sow is not None and sow >= t.material_share_of_wallet_pct:
        return RuleTest(
            "Materiality",
            True,
            f"{sow:g}% share of wallet, at or above the "
            f"{t.material_share_of_wallet_pct:g}% threshold",
        )
    shown = _money(premium, t.currency) if premium is not None else f"{sow:g}% share of wallet"
    return RuleTest("Materiality", False, f"{shown} is below the materiality threshold")


def test_magnitude(signals: WatchSignals, t: Thresholds) -> RuleTest:
    """Has the movement gone past the approved breach threshold?"""
    move = _adverse_move(signals)
    if move is None:
        return RuleTest("Magnitude", False, "No adverse movement reported")
    if move >= t.severe_move_pct:
        return RuleTest(
            "Magnitude",
            True,
            f"{move:.1f}% adverse movement breached the {t.severe_move_pct:g}% threshold",
        )
    return RuleTest(
        "Magnitude",
        False,
        f"{move:.1f}% adverse movement is under the {t.severe_move_pct:g}% threshold",
    )


def test_early_warning(signals: WatchSignals, t: Thresholds) -> RuleTest:
    """Has it crossed the softer watch level, short of a breach?"""
    move = _adverse_move(signals)
    if move is None:
        return RuleTest("Early warning", False, "No adverse movement reported")
    if move >= t.watch_move_pct:
        return RuleTest(
            "Early warning",
            True,
            f"{move:.1f}% adverse movement is at or above the {t.watch_move_pct:g}% watch level",
        )
    return RuleTest(
        "Early warning", False, f"{move:.1f}% adverse movement is below the watch level"
    )


def test_persistence(signals: WatchSignals, t: Thresholds) -> RuleTest:
    """One bad period, or a trend?"""
    periods = max(1, int(signals.consecutive_periods or 1))
    if periods >= t.persistent_periods:
        return RuleTest("Persistence", True, f"Adverse for {periods} consecutive periods")
    return RuleTest("Persistence", False, "A single-period movement")


def test_business_breach(signals: WatchSignals, _t: Thresholds) -> RuleTest:
    """Has a governed KPI (rank, broker score, share of wallet) crossed its target?"""
    kpi = (signals.breached_kpi or "").strip()
    if kpi:
        return RuleTest("Business breach", True, kpi)
    return RuleTest("Business breach", False, "No governed KPI target crossed")


def test_data_confidence(signals: WatchSignals, _t: Thresholds) -> RuleTest:
    """Are the periods complete and comparable enough to classify at all?"""
    if signals.periods_comparable:
        return RuleTest("Data confidence", True, "Periods are complete and comparable")
    return RuleTest("Data confidence", False, "Periods are incomplete or not comparable")


# ───────────────────────────── classification ──────────────────────────────


def classify(signals: WatchSignals, thresholds: Optional[Thresholds] = None) -> PriorityVerdict:
    """Label one watchlist item from the approved rules.

    High     - material AND a threshold breach, or material with two or more
               adverse signals.
    Medium   - one material adverse signal, or a repeated early-warning movement.
    Low      - below materiality, or a movement that crossed no threshold.
    Unrated  - the periods are not comparable, so no label can be defended.
    """
    t = thresholds or get_thresholds()
    material = test_materiality(signals, t)
    magnitude = test_magnitude(signals, t)
    early = test_early_warning(signals, t)
    persistence = test_persistence(signals, t)
    breach = test_business_breach(signals, t)
    confidence = test_data_confidence(signals, t)
    tests = (material, magnitude, early, persistence, breach, confidence)

    if not confidence.passed:
        return _verdict(UNRATED, confidence.detail, tests, t)

    adverse = [r for r in (magnitude, persistence, breach) if r.passed]
    if material.passed and magnitude.passed:
        return _verdict(HIGH, f"{material.detail}; {magnitude.detail}", tests, t)
    if material.passed and len(adverse) >= 2:
        return _verdict(HIGH, "; ".join(r.detail for r in adverse[:2]), tests, t)
    if material.passed and adverse:
        return _verdict(MEDIUM, f"{material.detail}; {adverse[0].detail}", tests, t)
    if material.passed and early.passed:
        return _verdict(MEDIUM, f"{material.detail}; {early.detail}", tests, t)
    if early.passed and persistence.passed:
        return _verdict(MEDIUM, f"{early.detail}; {persistence.detail}", tests, t)
    if adverse:
        return _verdict(LOW, f"{adverse[0].detail}, below materiality", tests, t)
    return _verdict(LOW, early.detail if early.passed else magnitude.detail, tests, t)


def signals_from_item(item: Dict[str, Any]) -> WatchSignals:
    """Read the extractor's dict into the rule engine's inputs."""
    return WatchSignals(
        premium_exposed=_optional_number(item.get("premium_exposed_value")),
        share_of_wallet_pct=_optional_number(item.get("share_of_wallet_pct")),
        movement_pct=_optional_number(item.get("movement_pct")),
        adverse=bool(item.get("adverse", True)),
        consecutive_periods=int(_number(item.get("consecutive_periods"), 1)),
        breached_kpi=str(item.get("breached_kpi") or ""),
        periods_comparable=bool(item.get("periods_comparable", True)),
    )


def rate_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach a rule-derived priority to every item, then rank them.

    Sort order is the roadmap's: premium exposed first, then magnitude, then
    persistence — so the biggest exposure leads the card whatever its label.
    """
    t = get_thresholds()
    rated = [
        {**item, **classify(signals_from_item(item), t).as_dict()} for item in items or []
    ]
    return sorted(rated, key=_rank_key, reverse=True)


# ───────────────────────────── helpers ──────────────────────────────


def _verdict(
    label: str, reason: str, tests: Tuple[RuleTest, ...], t: Thresholds
) -> PriorityVerdict:
    return PriorityVerdict(
        label=label, reason=reason, tests=tests, approved=t.approved, thresholds=t.summary()
    )


def _rank_key(item: Dict[str, Any]) -> Tuple[float, float, int]:
    return (
        _number(item.get("premium_exposed_value"), 0.0),
        abs(_number(item.get("movement_pct"), 0.0)),
        int(_number(item.get("consecutive_periods"), 1)),
    )


def _adverse_move(signals: WatchSignals) -> Optional[float]:
    """Adverse movement as a positive percentage, or None when there is none."""
    if signals.movement_pct is None or not signals.adverse:
        return None
    return abs(signals.movement_pct)


def _number(value: Any, default: float) -> float:
    parsed = _optional_number(value)
    return default if parsed is None else parsed


def _optional_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: Optional[float], currency: str) -> str:
    """Format a premium the way the widgets do, so the drawer matches the card."""
    if value is None:
        return "—"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get((currency or "").upper(), "")
    for unit, scale in (("bn", 1e9), ("m", 1e6), ("k", 1e3)):
        if abs(value) >= scale:
            return f"{symbol}{value / scale:.1f}{unit}"
    return f"{symbol}{value:,.0f}"


def format_money(value: Optional[float], currency: str = "") -> str:
    """Public formatter — the widgets and the PPT export share it for parity."""
    return _money(value, currency or get_thresholds().currency)
