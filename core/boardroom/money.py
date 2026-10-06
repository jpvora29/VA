"""How the Boardroom prints an amount — one formatter, screen and slide.

The board and the exported deck read the same premium figures, so they share the
formatter; a number that reads "£8.2m" on screen must read "£8.2m" on the slide.
The reporting currency is configuration rather than code, so it lives in
``money.yaml`` next to this module.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from core.analytics.money_units import money_text

from logger import get_logger

logger = get_logger(__name__)

_SETTINGS_PATH = Path(__file__).parent / "money.yaml"
_DEFAULT_CURRENCY = "GBP"
_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}


@lru_cache(maxsize=1)
def reporting_currency() -> str:
    """The currency premiums are reported in — configured, with a safe default."""
    try:
        settings = yaml.safe_load(_SETTINGS_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:  # noqa: BLE001 - config must never break a board
        logger.warning("Boardroom money settings unreadable (%s); using %s", exc, _DEFAULT_CURRENCY)
        return _DEFAULT_CURRENCY
    return str(settings.get("currency") or _DEFAULT_CURRENCY)


def currency_symbol(currency: str = "") -> str:
    """The symbol of ``currency`` (default: the reporting currency) — ``$``, ``£``, ``€``."""
    return _SYMBOLS.get((currency or reporting_currency()).upper(), "")


def format_money(value: Optional[float], currency: str = "") -> str:
    """A premium at board scale: ``£8.2m``, ``$412k``, ``€1.4bn``, ``—`` for nothing."""
    if value is None or value == "":
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    symbol = _SYMBOLS.get((currency or reporting_currency()).upper(), "")
    # Millions, or billions from 1bn — never thousands or raw units, so the
    # board, the slide and the chat state one amount the same way.
    return money_text(amount, symbol=symbol)
