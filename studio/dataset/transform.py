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


def apply_transforms(frame: pd.DataFrame, ops: Sequence[TransformOp]) -> pd.DataFrame:
    """Replay the shape recipe (in order) on a copy of the frame.

    Unknown drops are ignored; a failing add raises ``ValueError`` (the caller
    shows it and the recipe is not persisted).
    """
    out = frame.copy()
    for op in ops:
        if op.kind == "drop":
            out = out.drop(columns=[op.name], errors="ignore")
        elif op.kind == "add" and op.name:
            out[op.name] = safe_eval(out, op.formula)
    return out
