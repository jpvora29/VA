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


# Recipe id → (label, function). The UI reads this map for its dropdown, so a new
# reading is one entry here and nothing else.
RECIPES = {
    "year": ("Year from a date", _year),
    "quarter": ("Quarter from a date (2025-Q1)", _quarter),
    "month": ("Month from a date (2025-01)", _month),
    "month_name": ("Month name from a date", _month_name),
    "date": ("Clean date (YYYY-MM-DD)", _iso_date),
    "upper": ("Upper-case text", _upper),
    "trim": ("Trimmed text", _trimmed),
}


def derive_column(frame: pd.DataFrame, source: str, recipe: str) -> pd.Series:
    """Read a new column out of ``source`` using a named recipe.

    Raises ``ValueError`` — worded for the user — for an unknown recipe, a missing
    source column, or values the recipe cannot read.
    """
    if source not in frame.columns:
        raise ValueError(f"There is no column called {source!r}.")
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
            out[op.name] = derive_column(out, op.source, op.recipe)
    return out
