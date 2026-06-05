from typing import Callable, Any, Optional
from collections import defaultdict

from document_builder.helpers.number_formatter import (
    parse_signed_number,
    format_signed,
    format_money,
    format_pct,
)

_NUMERIC_METRIC_TOKENS = (
    "premium",
    "growth",
    "yoy",
    "sow",
    "share",
    "share of portfolio",
    "appetite",
    "score",
    "rank",
    "peer",
)

_IDENTITY_TOKENS = (
    "carrier",
    "country",
    "product",
    "section",
    "attribute",
    "lob",
    "line of business",
    "practice",
    "survey_practice",
    "survey practice",
    "segment",
    "source",
    "product_line",
    "surveypractice",
)

# --- Type aliases ---
Predicate = Callable[[str], bool]
Formatter = Callable[[Any], str]


# --- detect columns ---


def is_numeric_metric_header(header: str) -> bool:
    h = str(header).lower()
    if _is_year_header(header):
        return False
    return any(tok in h for tok in _NUMERIC_METRIC_TOKENS)


def is_identity_header(header: str) -> bool:
    h = str(header).lower()
    if _is_year_header(header):
        return False
    if is_numeric_metric_header(header):
        return False
    return any(tok in h for tok in _IDENTITY_TOKENS) or h == "source"


def _detect_shaded_columns(headers: list[str]) -> list[tuple[int, bool]]:
    """Columns to apply green/red shading on. (col_index, good_when_positive)"""
    shaded: list[tuple[int, bool]] = []
    for idx, h in enumerate(headers):
        hl = str(h).lower()
        is_delta = (
            "δ" in str(h)
            or "delta" in hl
            or " vs " in hl
            or hl.endswith(" vs")
            or "rank change" in hl
        )
        if is_delta:
            shaded.append((idx, "rank" not in hl))
            continue
        if "growth" in hl or "yoy" in hl:
            shaded.append((idx, True))
            continue
        if "rank" in hl and not _is_year_header(h):
            continue

    return shaded


# --- Formatter ---
def _format_rank_change(value: Any) -> str:
    n = parse_signed_number(value)
    return format_signed(n, 0) if n is not None else "-"


def _format_rank(value: Any) -> str:
    n = parse_signed_number(value)
    return f"#{int(n)}" if n is not None else "-"


def _format_share(value: Any) -> str:
    n = parse_signed_number(value)
    if n is None:
        return "-"
    if abs(n) <= 1.0:
        n *= 100
    return f"{n:,.1f}%"


def _format_score(value: Any) -> str:
    n = parse_signed_number(value)
    return f"{n:,.1f}" if n is not None else "-"


def _format_year(value: Any) -> str:
    n = parse_signed_number(value)
    # Years are plain integers — no thousands separators, no decimals.
    return f"{int(n)}" if n is not None else "-"


def _is_year_header(header: str) -> bool:
    h = str(header).strip().lower().replace(" ", "_")
    return h in {"year", "survey_year", "fiscal_year", "fy"}


# --- Predicate → Formatter dispatch table ---
_HEADER_RULES: list[tuple[Predicate, Formatter]] = [
    (
        _is_year_header,
        _format_year,
    ),
    (
        lambda h: any(
            tok in h for tok in ("delta rank", "rank_change", "δ rank", "Δ rank")
        )
        or ("rank" in h and any(tok in h for tok in ("δ", "change", "delta"))),
        _format_rank_change,
    ),
    (
        lambda h: "rank" in h,
        _format_rank,
    ),
    (
        lambda h: "growth" in h or "yoy" in h or h.endswith("_pct") or h.endswith(" %"),
        format_pct,
    ),
    (
        lambda h: "premium" in h or h == "gwp",
        format_money,
    ),
    (
        lambda h: any(
            tok in h
            for tok in ("share", "sow", "wallet", "appetite", "share of portfolio")
        ),
        _format_share,
    ),
    (
        lambda h: "score" in h,
        _format_score,
    ),
]


# --- Main dispatch function ---


def format_by_header(header: str, value: Any) -> str:
    """Format a cell value based on what its column represents."""
    if value is None or value == "":
        return "-"

    h = str(header).lower()

    for predicate, formatter in _HEADER_RULES:
        if predicate(h):
            return formatter(value)

    return str(value)  # default fallback


def _pivot_by_year(
    headers: list[str], rows: list[dict[str, Any]]
) -> Optional[tuple[list[str], list[list[Any]]]]:
    """Pivot a long-format block (one row per entity per year) into wide format."""

    year_col = next((h for h in headers if _is_year_header(h)), None)
    if not year_col:
        return None

    years_seen: list[Any] = []
    for r in rows:
        y = parse_signed_number(r.get(year_col))
        if y is None:
            continue
        yi = int(y)
        if yi not in years_seen:
            years_seen.append(yi)

    if len(years_seen) < 2:
        return None

    identity_cols = [
        h for h in headers if h != year_col and not is_numeric_metric_header(h)
    ]
    # if not identity_cols:
    #     identity_cols = [
    #         h for h in headers if h != year_col and not _is_numeric_metric_header(h)
    #     ]
    metric_cols = [h for h in headers if h != year_col and is_numeric_metric_header(h)]
    if not identity_cols or not metric_cols:
        return None

    # Group rows by identity tuple
    grouped: "dict[tuple[Any, ...], dict[int, dict[str, Any]]]" = defaultdict(dict)
    order: list[tuple[Any, ...]] = []
    for r in rows:
        y = parse_signed_number(r.get(year_col))
        if y is None:
            continue
        yi = int(y)
        key = tuple(str(r.get(c, "")) for c in identity_cols)
        if key not in grouped:
            order.append(key)
        grouped[key][yi] = r

    # Confirm at least one entity actually has rows in >1 year
    if not any(len(v) > 1 for v in grouped.values()):
        return None

    sorted_years = sorted(years_seen)
    new_headers: list[str] = list(identity_cols)
    for m in metric_cols:
        for y in sorted_years:
            new_headers.append(f"{m} {y}")

    # Add a growth $ column if not present and we have >=2 years
    has_premium = any(
        "premium" in m.lower() and ("growth" not in m.lower() or "yoy" not in m.lower())
        for m in metric_cols
    )
    growth_col_idx: Optional[int] = None
    if has_premium and len(sorted_years) >= 2:
        new_headers.append("Growth %")
        growth_col_idx = len(new_headers) - 1

    out_rows: list[list[Any]] = []
    curr_year = sorted_years[-1]
    prev_year = sorted_years[-2] if len(sorted_years) >= 2 else None

    for key in order:
        per_year = grouped[key]
        cells: list[Any] = []
        for col, val in zip(identity_cols, key):
            cells.append(format_by_header(col, val))
        for m in metric_cols:
            for y in sorted_years:
                row_for_year = per_year.get(y, {})
                cells.append(format_by_header(m, row_for_year.get(m, "")))

        if growth_col_idx is not None and prev_year is not None:
            curr_row = per_year.get(curr_year, {})
            prev_row = per_year.get(prev_year, {})
            premium_key = next(
                (
                    m
                    for m in metric_cols
                    if "premium" in m.lower() and "growth" not in m.lower()
                ),
                None,
            )
            growth_val: Any = ""

            for k in curr_row.keys():
                kl = str(k).lower()
                if "growth" in kl and (
                    "percent" in kl or "pct" in kl or "%" in kl or "yoy" in kl
                ):
                    gv = parse_signed_number(curr_row.get(k))
                    if gv is not None:
                        growth_val = gv
                        break
            if growth_val == "" and premium_key:
                pc = parse_signed_number(curr_row.get(premium_key))
                pp = parse_signed_number(prev_row.get(premium_key))
                if pc is not None and pp not in (None, 0):
                    growth_val = (pc - pp) / pp * 100
            cells.append(format_pct(growth_val) if growth_val != "" else "-")

        out_rows.append(cells)

    return new_headers, out_rows


def _format_cell_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if value != value:  # NaN
            return "—"
        return f"{value:,.2f}" if abs(value - int(value)) > 1e-9 else f"{int(value):,}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def ordered_rows_from_query_result(
    query_result: Any,
) -> list[tuple[list[str], list[dict[str, Any]]]]:
    """Return list of (column_order, rows) tuples preserving SQL column order"""

    blocks: list[tuple[list[str], list[dict[str, Any]]]] = []
    if not query_result:
        return blocks

    def _block_from_list(rows: Any) -> Optional[tuple[list[str], list[dict[str, Any]]]]:
        if not isinstance(rows, list):
            return None
        dict_rows = [r for r in rows if isinstance(r, dict)]
        if not dict_rows:
            return None
        order: list[str] = []
        seen: set = set()
        for r in dict_rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    order.append(str(k))
        return order, dict_rows

    if isinstance(query_result, list):
        blk = _block_from_list(query_result)
        if blk:
            blocks.append(blk)
        return blocks

    if isinstance(query_result, dict):
        if "premium" in query_result or "survey" in query_result:
            for key in ("premium", "survey"):
                blk = _block_from_list(query_result.get(key))
                if blk:
                    blocks.append(blk)
            return blocks
        for value in query_result.values():
            blk = _block_from_list(value)
            if blk:
                blocks.append(blk)
        return blocks

    return blocks


def rows_to_styled_table(
    query_result: Any,
) -> tuple[list[str], list[list[Any]], list[tuple[int, bool]]]:
    blocks = ordered_rows_from_query_result(query_result)
    if not blocks:
        return [], [], []

    if len(blocks) == 1:
        headers, rows = blocks[0]
        pivoted = _pivot_by_year(headers, rows)
        if pivoted is not None:
            new_headers, out_rows = pivoted
            return new_headers, out_rows, _detect_shaded_columns(new_headers)

        out_rows = [[_format_cell_value(r.get(h, "")) for h in headers] for r in rows]
        return headers, out_rows, _detect_shaded_columns(headers)

    # Two blocks (premium + survey) - try pivoting each, else merge long-format.
    pivoted_blocks: list[tuple[list[str], list[list[Any]]]] = []
    any_pivot = False
    for headers, rows in blocks:
        pv = _pivot_by_year(headers, rows)
        if pv is not None:
            pivoted_blocks.append(pv)
            any_pivot = True
        else:
            pivoted_blocks.append(
                (
                    headers,
                    [
                        [format_by_header(h, r.get(h, "")) for h in headers]
                        for r in rows
                    ],
                )
            )

    if any_pivot:
        merged_order: list[str] = ["Source"]
        seen: set = {"Source"}
        for hdrs, _ in pivoted_blocks:
            for h in hdrs:
                seen.add(h)
                merged_order.append(h)
        out_rows: list[list[Any]] = []
        labels = ["Premium", "Survey"]
        for label, (hdrs, rs) in zip(labels, pivoted_blocks):
            idx_for = {h: i for i, h in enumerate(hdrs)}
            for r in rs:
                cells: list[Any] = []
                for h in merged_order:
                    if h == "Source":
                        cells.append(label)
                    elif h in hdrs:
                        cells.append(r[idx_for[h]])
                    else:
                        cells.append("-")
                out_rows.append(cells)
        return merged_order, out_rows, _detect_shaded_columns(merged_order)

    merged_order: list[str] = ["Source"]
    seen: set = {"Source"}
    for headers, _ in blocks:
        for h in headers:
            if h not in seen:
                seen.add(h)
            merged_order.append(h)

    out_rows: list[list[Any]] = []
    labels = ["Premium", "Survey"]
    for label, (_, rows) in zip(labels, blocks):
        for r in rows:
            cells: list[Any] = []
            for h in merged_order:
                if h == "Source":
                    cells.append(label)
                else:
                    cells.append(_format_cell_value(r.get(h, "")))
            out_rows.append(cells)
    return merged_order, out_rows, _detect_shaded_columns(merged_order)
