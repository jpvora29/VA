"""Drop commentary lines that only restate figures the deck has already given.

The editorial plan (:mod:`studio.template_fill.editorial`) decides which field owns which
finding before anything is written, and its gate holds the model to it — but only for
claims it can identify, and only on the model path. What still reached the Overall pages
was the same headline said three ways: "grew 28.6% to $208M" on the highlights page, "wrote
$208M, up 28.6%" in Key Messages, and again in the ranking page's Key Highlights; the
9.1% share of wallet in three fields; "defend Cyber … #1" twice inside one field.

Every one of those repeats restates NUMBERS already on an earlier page. So the identity
used here is the figures themselves: reading the sub-deck in page order, a line that adds
no figure the reader has not already been given is a repeat, and goes. A line with no
figures at all is kept — there is nothing here to judge it by. A field is never emptied:
when every line of it would go, its first line stays, because a blank box on a slide
reads as a broken deck, not as a tidy one.

Pure: ``{role: text}`` in, ``{role: text}`` out, deterministic, no model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Mapping, Tuple

from logger import get_logger

logger = get_logger(__name__)

_MONEY = re.compile(
    r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(bn|billion|b|m|million|mn|k|thousand)?\b", re.I)
_PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)\s?(%|percent\b)", re.I)
_POINTS = re.compile(r"(-?\d+(?:\.\d+)?)\s?(pp\b|percentage points?\b|pts?\b)", re.I)
_RANK = re.compile(r"(?:#\s?(\d+)\b|\b(\d+)(?:st|nd|rd|th)\b)", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z&'’]*")

_SCALE = {"bn": 1000.0, "billion": 1000.0, "b": 1000.0, "m": 1.0, "million": 1.0,
          "mn": 1.0, "k": 0.001, "thousand": 0.001}

# Capitalised words that start sentences rather than name anything.
_GENERIC = frozenset({
    "a", "an", "the", "its", "it", "at", "in", "on", "by", "and", "but", "so", "this",
    "that", "these", "those", "carrier", "rank", "ranked", "writing", "matching", "with",
    "while", "where", "share", "penetration", "growth", "premium", "key", "highlights",
})


@dataclass(frozen=True)
class Figure:
    """One number as a reader takes it in: what kind, and its value at reading precision.

    Ranks are weak — "#1" in Cyber and "#1" in Property are different findings — so they
    carry the line's named things and only match a rank seen beside one of them.
    """

    kind: str
    value: str


def _sig(value: float) -> str:
    """Three significant figures: "$207.9M" and "$208M" are the same figure on a slide."""
    return f"{float(f'{value:.3g}'):g}"


def figures_of(line: str) -> Tuple[Figure, ...]:
    """Every money, percentage, point and rank figure in ``line``, in reading order."""
    out: List[Figure] = []
    for number, unit in _MONEY.findall(line):
        millions = float(number.replace(",", "")) * _SCALE.get((unit or "").lower(), 1e-6)
        out.append(Figure("money", _sig(millions)))
    for number, _unit in _PERCENT.findall(line):
        out.append(Figure("pct", f"{float(number):.1f}"))
    for number, _unit in _POINTS.findall(line):
        out.append(Figure("pp", f"{float(number):.1f}"))
    for hash_rank, ordinal in _RANK.findall(line):
        out.append(Figure("rank", hash_rank or ordinal))
    return tuple(out)


def names_of(line: str) -> FrozenSet[str]:
    """The capitalised things a line names (Cyber, Zurich, Property), lower-cased."""
    words = (w for w in _WORD.findall(line.replace("-", " ")) if w[0].isupper())
    return frozenset(w.lower() for w in words if w.lower() not in _GENERIC)


class _Seen:
    """What the reader has been given so far: every figure, and where each rank stood."""

    def __init__(self) -> None:
        self._figures: set = set()
        self._rank_names: Dict[str, set] = {}

    def knows(self, figure: Figure, names: FrozenSet[str]) -> bool:
        if figure.kind == "rank":
            return bool(self._rank_names.get(figure.value, set()) & names)
        return figure in self._figures

    def add(self, figures: Tuple[Figure, ...], names: FrozenSet[str]) -> None:
        for figure in figures:
            self._figures.add(figure)
            if figure.kind == "rank":
                self._rank_names.setdefault(figure.value, set()).update(names)


def is_repeat(line: str, seen: _Seen) -> bool:
    """True when ``line`` has figures and the reader already has every one of them."""
    figures = figures_of(line)
    names = names_of(line)
    return bool(figures) and all(seen.knows(f, names) for f in figures)


def role_order(role: str) -> Tuple[int, ...]:
    """Page order for a commentary role: ``note:<slide>:<shape>:…`` → (slide, shape, …).

    Roles that are not slide-addressed sort last, in their original order.
    """
    parts = role.split(":")[1:]
    if parts and all(p.isdigit() for p in parts):
        return (0, *(int(p) for p in parts))
    return (1,)


def _lines(text: str) -> List[str]:
    return [line for line in str(text or "").split("\n")]


def _keep_lines(lines: List[str], seen: _Seen) -> List[str]:
    """The lines of one field that add something, never fewer than one worded line.

    Judged and recorded one line at a time, so a field that says a thing twice loses
    the second saying too.
    """
    kept: List[str] = []
    for line in lines:
        if line.strip() and is_repeat(line, seen):
            continue
        kept.append(line)
        seen.add(figures_of(line), names_of(line))
    if not any(line.strip() for line in kept):
        kept = [next((line for line in lines if line.strip()), "")]
    return kept


def prune_repeats(texts: Mapping[str, str], *, label: str = "") -> Dict[str, str]:
    """``texts`` with every line that only restates earlier figures removed.

    Read in page order (:func:`role_order`); the first statement of a figure keeps it.
    """
    out = dict(texts)
    seen = _Seen()
    dropped = 0
    for role in sorted(texts, key=role_order):
        lines = _lines(texts[role])
        kept = _keep_lines(lines, seen)
        if len(kept) != len(lines):
            dropped += len(lines) - len(kept)
            out[role] = "\n".join(kept)
    if dropped:
        logger.info("repeat_prune%s: dropped %d line(s) that restated earlier figures",
                    f" [{label}]" if label else "", dropped)
    return out


__all__ = ["Figure", "figures_of", "names_of", "is_repeat", "prune_repeats", "role_order"]
