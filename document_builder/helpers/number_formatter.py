from typing import Any, Optional
import re

# --- Formatter helpers ---------------------------------------


def parse_signed_number(text: str) -> Optional[float]:
    """Parse a number out of messy text, PRESERVING sign and decimals.

    Handles thousands separators, currency symbols/codes ("$", "USD"), "%",
    units, and both leading-minus and accounting-style "(1,234.5)" negatives.

    The previous implementation stripped everything except digits and "+"
    (``[^\\d+]+``), which silently deleted the decimal point and the minus sign —
    turning "57,616,719.76" into 5,761,671,976 and "-9.25%" into +925. That single
    defect is what made the KPI premium, YoY growth, and survey score all wrong.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None

    # Negative when a '-' precedes the first digit, or the value is parenthesised.
    first_digit = re.search(r"\d", s)
    if first_digit is None:
        return None
    prefix = s[: first_digit.start()]
    negative = "-" in prefix or (s.startswith("(") and s.rstrip().endswith(")"))

    # Keep only digits and the decimal point; drop currency, commas, %, units, signs.
    cleaned = re.sub(r"[^\d.]", "", s)
    # If multiple dots survive odd input, treat the last as the decimal separator.
    if cleaned.count(".") > 1:
        head, _, tail = cleaned.rpartition(".")
        cleaned = head.replace(".", "") + "." + tail
    if not cleaned or cleaned == ".":
        return None

    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if negative else value


def format_pct(value: Any, with_sign: bool = True) -> str:
    n = parse_signed_number(value)
    if n is None:
        return "-"
    sign = "+" if (with_sign and n > 0) else ""
    return f"{sign}{n:,.1f}"


def format_money(value: Any) -> str:
    n = parse_signed_number(value)
    if n is None:
        return "-"
    if abs(n) >= 1_000_000_000:
        return f"${n / 1_000_000_000:,.2f}B"
    if abs(n) >= 1_000_000:
        return f"${n / 1_000_000:,.2f}M"
    if abs(n) >= 1_000:
        return f"${n / 1_000:,.1f}K"
    return f"${n:,.0f}"


def format_signed(value: Any, decimals: int = 1) -> str:
    n = parse_signed_number(value)
    if n is None:
        return "-"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:,.{decimals}f}"


def coerce_kpi_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    return parse_signed_number(text)
