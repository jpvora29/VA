from typing import Any, Optional

# --- Formatter helpers ---------------------------------------


def parse_signed_number(text: str) -> Optional[float]:
    if text is None:
        return None
    s = (
        str(text)
        .strip()
        .replace(",", "")
        .replace("%", "")
        .replace("USD", "")
        .replace("$", "")
    )
    if not s or s in {"-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


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
