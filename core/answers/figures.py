"""The figures an answer states, and whether the evidence contains them.

Every number in a written answer is a claim. This module makes that claim
checkable: it pulls the numeric tokens out of the prose, pulls them out of the
result rows the turn actually ran, and normalises both to the same form so they
can be compared.

Normalisation is the whole trick. The writer says "$8.2m" and the row holds
`8200000`; the writer says "19.5%" and the row holds `19.5`. Comparing raw text
would fail on both. So a token is reduced to a canonical numeric string, and a
scaled figure (m / bn / k) is ALSO expanded, so "$8.2m" matches `8200000` without
the checker having to guess which form the writer chose.

Deliberately not a validator: it reports what matched and what did not. Dropping
a sentence is Studio's job (`studio.ai.verifier`, which reuses the tokeniser
here); a chat answer states its check and lets the reader see it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

# A numeric token: optional #/sign/currency, digits (with commas/decimal), an
# optional unit suffix (%, x, pts, m, bn, b, k).
NUMERIC_TOKEN = re.compile(
    r"[#+\-]?\s*(?:usd\s*|eur\s*|gbp\s*|[$£€])?\d[\d,]*(?:\.\d+)?\s*(?:%|x|pp|pts|bn|b|m|k)?",
    re.I,
)

# Suffix -> what it multiplies by, for the expanded form of a scaled figure.
_SCALES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "bn": 1_000_000_000}

# Figures this small are ordinals and list positions ("the top 3", "2 of 5"),
# not measures. Checking them produces noise, not assurance.
_TRIVIAL = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}

# A year is scope, not a measure — it is checked by the scope chips, and it very
# often will not appear as a VALUE in the rows (it is a filter).
_YEAR = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class Figure:
    """One numeric token from an answer, and whether the evidence has it."""

    text: str          # exactly as written, e.g. "$8.2m"
    value: str         # normalised, e.g. "8.2m"
    supported: bool = False

    @property
    def is_checkable(self) -> bool:
        """False for ordinals and years — see `_TRIVIAL` / `_YEAR`."""
        return not (self.value in _TRIVIAL or _YEAR.match(self.value))


def normalise(token: str) -> str:
    """A numeric token reduced to a comparable form.

    Currency marks, thousands separators, leading `#`/`+` and whitespace go; the
    unit suffix stays, because "12" and "12%" are different claims.
    """
    text = str(token or "").lower().strip()
    for junk in ("usd", "eur", "gbp", "$", "£", "€", ",", " ", "#", "+"):
        text = text.replace(junk, "")
    text = text.lstrip("-").strip()
    return text.rstrip(".") if text.endswith(".") else text


def forms_of(token: str) -> Set[str]:
    """Every form a figure could legitimately be written in.

    "8.2m" also matches a row holding 8200000, and "19.5%" also matches 19.5 —
    the writer scales and suffixes for readability, and the row does not.
    """
    value = normalise(token)
    if not value:
        return set()
    forms = {value}
    match = re.match(r"^(\d+(?:\.\d+)?)(bn|b|m|k|%|x|pp|pts)?$", value)
    if not match:
        return forms
    number, suffix = match.group(1), (match.group(2) or "")
    forms.add(number)  # the bare number, without its unit
    scale = _SCALES.get(suffix)
    if scale:
        expanded = float(number) * scale
        forms.add(_plain(expanded))
    return forms


def _plain(number: float) -> str:
    """A float as the shortest exact string — 8200000.0 -> "8200000"."""
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


def figures_in(text: str) -> List[Figure]:
    """Every numeric token in the answer, in the order it was written."""
    seen: Set[str] = set()
    out: List[Figure] = []
    for match in NUMERIC_TOKEN.finditer(text or ""):
        raw = match.group(0).strip()
        value = normalise(raw)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(Figure(text=raw, value=value))
    return out


def values_in_rows(rows: Iterable[Mapping[str, Any]]) -> Set[str]:
    """Every numeric form present in a result set.

    Each cell contributes its exact value AND its rounded forms: a row holding
    8_237_411.0 supports an answer that says "$8.2m", which is the number a
    person would actually write.
    """
    out: Set[str] = set()
    for row in rows or []:
        values = row.values() if isinstance(row, Mapping) else [row]
        for cell in values:
            out |= _forms_of_cell(cell)
    return out


def _forms_of_cell(cell: Any) -> Set[str]:
    """The comparable forms of one result cell."""
    if isinstance(cell, bool) or cell is None:
        return set()
    if isinstance(cell, str):
        # A string cell can still hold a figure ("£8.2m" from a display column).
        return {form for token in NUMERIC_TOKEN.finditer(cell) for form in forms_of(token.group(0))}
    try:
        number = float(cell)
    except (TypeError, ValueError):
        return set()
    forms = {_plain(number)}
    for places in (0, 1, 2):
        forms.add(_plain(round(number, places)))
    # The scaled readings a writer would use.
    #
    # Not gated on the number reaching the scale: 940,000 is written "$0.9m" all
    # the time, and requiring >= 1,000,000 to offer an "m" form flagged that as
    # unsupported. The floor is instead the point below which the reading stops
    # being meaningful — 0.1 of the unit, so 5 never becomes "0.0m".
    for suffix, scale in (("k", 1_000), ("m", 1_000_000), ("bn", 1_000_000_000)):
        scaled = round(number / scale, 1)
        if abs(scaled) < 0.1:
            continue
        forms.add(f"{_plain(scaled)}{suffix}")
        forms.add(_plain(scaled))
        whole = round(number / scale)
        if whole:
            forms.add(f"{_plain(whole)}{suffix}")
    # A ratio stored as 0.195 is written as 19.5%.
    if abs(number) <= 1:
        forms.add(f"{_plain(round(number * 100, 1))}%")
    forms.add(f"{_plain(round(number, 1))}%")
    return forms


def check(text: str, rows_by_lens: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[Figure]:
    """Each figure in the answer, marked with whether the evidence contains it.

    Checked against EVERY lens's rows together: a combined answer legitimately
    quotes a premium figure from one query and a survey score from another.
    """
    supported: Set[str] = set()
    for rows in (rows_by_lens or {}).values():
        supported |= values_in_rows(rows)
    return [
        Figure(text=f.text, value=f.value, supported=bool(forms_of(f.value) & supported))
        for f in figures_in(text)
    ]


def unsupported(figures: Sequence[Figure]) -> List[Figure]:
    """The checkable figures the evidence does not contain."""
    return [f for f in figures if f.is_checkable and not f.supported]


def coverage(figures: Sequence[Figure]) -> Dict[str, int]:
    """How many checkable figures there were, and how many were found."""
    checkable = [f for f in figures if f.is_checkable]
    return {
        "checkable": len(checkable),
        "supported": len([f for f in checkable if f.supported]),
    }
