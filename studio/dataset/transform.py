"""Pure column operations on the working frame — add computed, drop, evaluate.

Formulas are plain arithmetic over existing columns (``Premium * 0.1``,
``Written + Fees``). ``safe_eval`` whitelists the characters and hands the
expression to ``DataFrame.eval`` — no builtins, no attribute access, no calls,
so a formula can only ever combine columns and numbers.
"""
from __future__ import annotations

import re
from typing import Sequence

import pandas as pd

from studio.dataset.model import TransformOp

# Column tokens, numbers, arithmetic, parentheses, backticks (df.eval quoting
# for names with spaces). No quotes, no @, no dots-into-attributes beyond
# decimal points, no brackets — nothing that reaches outside the frame.
_FORMULA_RE = re.compile(r"^[A-Za-z0-9_ \t`.+\-*/() ]+$")
_CALL_RE = re.compile(r"[A-Za-z_`][A-Za-z0-9_ ]*`?\s*\(")  # name immediately before ( = a call


def _quoted(formula: str, columns: Sequence[str]) -> str:
    """Backtick-quote column names containing spaces so ``df.eval`` accepts them."""
    out = formula
    for col in sorted(columns, key=len, reverse=True):
        if " " in col and col in out and f"`{col}`" not in out:
            out = out.replace(col, f"`{col}`")
    return out


def safe_eval(frame: pd.DataFrame, formula: str) -> pd.Series:
    """Evaluate an arithmetic formula over the frame's columns.

    Raises ``ValueError`` on anything but plain column arithmetic, so a bad
    formula surfaces as a friendly message rather than arbitrary evaluation.
    """
    expr = (formula or "").strip()
    if not expr:
        raise ValueError("Formula is empty.")
    if not _FORMULA_RE.match(expr):
        raise ValueError("Formula may only use column names, numbers and + - * / ( ).")
    if _CALL_RE.search(expr):
        raise ValueError("Function calls are not allowed in formulas.")
    try:
        result = frame.eval(_quoted(expr, list(frame.columns)), engine="python")
    except Exception as exc:  # noqa: BLE001 — surface pandas' reason, friendly
        raise ValueError(f"Formula failed: {exc}") from exc
    if not isinstance(result, pd.Series):
        raise ValueError("Formula must produce one value per row.")
    return result


# ── derived columns: read one column out of another ──────────────────────────
#
# The case that made this necessary: a spreadsheet carries a billing DATE and no Year
# column, so nothing could map to Year and every period comparison in the deck went
# quiet. Recipes are named, pure and reversible-by-deletion — never a hand-typed
# expression the user has to get right.


def _dates(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.isna().all():
        raise ValueError("That column does not read as dates.")
    return parsed


def _year(series: pd.Series) -> pd.Series:
    return _dates(series).dt.year.astype("Int64")


def _quarter(series: pd.Series) -> pd.Series:
    dates = _dates(series)
    return dates.dt.year.astype("Int64").astype(str) + "-Q" + dates.dt.quarter.astype("Int64").astype(str)


def _month(series: pd.Series) -> pd.Series:
    return _dates(series).dt.strftime("%Y-%m")


def _month_name(series: pd.Series) -> pd.Series:
    return _dates(series).dt.strftime("%B")


def _iso_date(series: pd.Series) -> pd.Series:
    return _dates(series).dt.strftime("%Y-%m-%d")


def _upper(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.upper()


def _trimmed(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def _quarter_label(series: pd.Series) -> pd.Series:
    return "Q" + _dates(series).dt.quarter.astype("Int64").astype(str)


_MONTH_NUMBER = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
    start=1)}


def _quarter_from_month_name(series: pd.Series) -> pd.Series:
    months = series.astype(str).str.strip().str.lower().str[:3].map(_MONTH_NUMBER)
    if months.isna().all():
        raise ValueError("That column does not read as month names.")
    quarters = ((months + 2) // 3).astype("Int64").astype(str)
    return ("Q" + quarters).where(months.notna())


def _lower(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower()


def _title(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.title()


def _number(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


# Recipe id → (label, function). The UI reads this map for its dropdown, so a new
# reading is one entry here and nothing else.
RECIPES = {
    "year": ("Year from a date", _year),
    "quarter_label": ("Quarter from a date (Q1)", _quarter_label),
    "quarter": ("Quarter from a date (2025-Q1)", _quarter),
    "quarter_from_month": ("Quarter from a month name (Q1)", _quarter_from_month_name),
    "month": ("Month from a date (2025-01)", _month),
    "month_name": ("Month name from a date", _month_name),
    "date": ("Clean date (YYYY-MM-DD)", _iso_date),
    "number": ("Number from text (drops $ , % and letters)", _number),
    "upper": ("Upper-case text", _upper),
    "lower": ("Lower-case text", _lower),
    "title": ("Title Case text", _title),
    "trim": ("Trimmed text", _trimmed),
}


# ── readings that take settings: split, combine, replace, first/last characters ──
#
# Each takes the frame (``combine`` reads a second column), the source column and the
# settings the author typed, and names what its two setting boxes are for — the Data page
# relabels the boxes when the reading is picked.


def _part_index(raw: str) -> int:
    """"2" → the 2nd part; "-1" or "last" → the last. Parts count from 1, as people do."""
    text = str(raw or "1").strip().lower()
    if text in ("last", "end"):
        return -1
    try:
        n = int(text)
    except ValueError as exc:
        raise ValueError("Which part? Use 1 for the first, 2 for the second, -1 for the "
                         "last.") from exc
    if n == 0:
        raise ValueError("Parts count from 1 (or -1 for the last).")
    return n - 1 if n > 0 else n


def _split(frame: pd.DataFrame, source: str, args) -> pd.Series:
    delimiter = (args[0] if args else "") or " "
    index = _part_index(args[1] if len(args) > 1 else "1")
    parts = frame[source].astype(str).str.split(delimiter, regex=False)
    return parts.str[index].str.strip()


def _combine(frame: pd.DataFrame, source: str, args) -> pd.Series:
    other = (args[0] if args else "").strip()
    if other not in frame.columns:
        raise ValueError(f"Name the second column to combine with — {other!r} is not one.")
    joiner = args[1] if len(args) > 1 and args[1] else " "
    return (frame[source].astype(str).str.strip() + joiner
            + frame[other].astype(str).str.strip())


def _replace(frame: pd.DataFrame, source: str, args) -> pd.Series:
    find = args[0] if args else ""
    if not find:
        raise ValueError("Type the text to find.")
    return frame[source].astype(str).str.replace(find, args[1] if len(args) > 1 else "",
                                                 regex=False)


def _count(raw: str) -> int:
    try:
        n = int(str(raw or "").strip())
    except ValueError as exc:
        raise ValueError("How many characters? Type a whole number.") from exc
    if n <= 0:
        raise ValueError("How many characters? Type a number above 0.")
    return n


def _first(frame: pd.DataFrame, source: str, args) -> pd.Series:
    return frame[source].astype(str).str[:_count(args[0] if args else "")]


def _last(frame: pd.DataFrame, source: str, args) -> pd.Series:
    return frame[source].astype(str).str[-_count(args[0] if args else ""):]


# Recipe id → (label, function, (what setting 1 is, what setting 2 is)).
PARAM_RECIPES = {
    "split": ("Split by a delimiter — keep one part", _split,
              ("Delimiter (e.g. - or ,)", "Part: 1, 2 … or -1 for the last")),
    "combine": ("Combine with another column", _combine,
                ("The other column's name", "Separator (default: a space)")),
    "replace": ("Find and replace text", _replace, ("Find", "Replace with")),
    "first": ("First N characters", _first, ("How many characters", "")),
    "last": ("Last N characters", _last, ("How many characters", "")),
}


def recipe_label(recipe: str) -> str:
    entry = RECIPES.get(recipe) or PARAM_RECIPES.get(recipe)
    return entry[0] if entry else recipe


def derive_column(frame: pd.DataFrame, source: str, recipe: str, args=()) -> pd.Series:
    """Read a new column out of ``source`` using a named recipe (and its settings).

    Raises ``ValueError`` — worded for the user — for an unknown recipe, a missing
    source column, bad settings, or values the recipe cannot read.
    """
    if source not in frame.columns:
        raise ValueError(f"There is no column called {source!r}.")
    if recipe in PARAM_RECIPES:
        return PARAM_RECIPES[recipe][1](frame, source, tuple(args or ()))
    entry = RECIPES.get(recipe)
    if entry is None:
        raise ValueError(f"Unknown recipe {recipe!r}.")
    return entry[1](frame[source])


def apply_transforms(frame: pd.DataFrame, ops: Sequence[TransformOp]) -> pd.DataFrame:
    """Replay the shape recipe (in order) on a copy of the frame.

    Unknown drops are ignored; a failing add/derive raises ``ValueError`` (the caller
    shows it and the recipe is not persisted).
    """
    out = frame.copy()
    for op in ops:
        if op.kind == "drop":
            out = out.drop(columns=[op.name], errors="ignore")
        elif op.kind == "add" and op.name:
            out[op.name] = safe_eval(out, op.formula)
        elif op.kind == "derive" and op.name:
            out[op.name] = derive_column(out, op.source, op.recipe, op.args)
    return out
