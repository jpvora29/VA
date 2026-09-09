"""The finding, pulled to the front of the answer.

An answer that opens with a paragraph makes the reader find the conclusion inside
it. The conclusion is almost always the first sentence, so it is *set* as the
conclusion — one large line — with the rest of that paragraph as the line under
it and the remaining prose unchanged below.

This is typography, not summarisation. Nothing is written here that the answer did
not already say, and nothing is dropped: `Lead.headline`, `Lead.standfirst` and
`Lead.body` reassemble into the original text. When the answer does not open with
a sentence worth setting large — it starts with a heading, a bullet, a table, or a
sentence too long to be a headline — the lead is empty and the whole answer
renders exactly as it did before.

The key figures beside it come from the turn's own decomposition
(:mod:`core.answers.contribution`), which is arithmetic over the returned rows.
No figure is invented, and an answer with no decomposition simply shows none.

Pure: strings and dicts in, dataclasses out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.boardroom.money import format_money

# Past this many characters the first sentence is a paragraph wearing a full
# stop, and setting it at headline size makes the answer harder to read, not
# easier.
_HEADLINE_MAX = 190

# …and under this it is a fragment ("Yes.", "It fell."), which reads as a
# shouted stub rather than a finding.
_HEADLINE_MIN = 14

# A sentence ends at .?! followed by whitespace. Two things wear a full stop
# without being one, and each gets a guard:
#
#   a decimal point   "$112.4M"     -- has no space after it, so (?=\s) excludes it
#   an abbreviation   "the U.S. is" -- ends in a lone capital, which the lookbehind
#                                      rejects (it also catches an initial, "J. Smith")
#
# The digit before the stop is NOT excluded: "premium grew in Q2." is an ordinary
# sentence, and rejecting it left the whole first paragraph as the headline.
_SENTENCE_END = re.compile(r"(?<![\s.][A-Z])(?<=[^\s])[.!?](?=\s)")

# Markdown that means nothing once the text is set as a headline.
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)")

# Lines that are not prose: the answer is structured from its first line and has
# no lead paragraph to promote.
_NOT_PROSE = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|\||>|```)")


@dataclass(frozen=True)
class Lead:
    """An answer split into the conclusion, its qualifier, and the rest."""

    headline: str = ""
    standfirst: str = ""
    body: str = ""

    @property
    def has_headline(self) -> bool:
        return bool(self.headline)


def _clean(text: str) -> str:
    """Headline text: emphasis markers gone, whitespace collapsed."""
    return " ".join(_EMPHASIS.sub("", text).split())


def split_lead(markdown: str) -> Lead:
    """Split an answer into its finding, the qualifying line, and the body.

    The lead can only come from a first paragraph of plain prose. Anything else
    — a heading, a bullet, a table, a quote, a fence — is already structured, and
    re-cutting it here would break the structure the writer chose.
    """
    text = (markdown or "").strip()
    if not text or _NOT_PROSE.match(text):
        return Lead(body=markdown or "")

    paragraph, _, rest = text.partition("\n\n")
    if "\n" in paragraph.strip():
        # A "paragraph" with a hard break inside it is a list or an address, not
        # prose with a first sentence.
        return Lead(body=markdown or "")

    match = _SENTENCE_END.search(paragraph)
    first = paragraph[: match.end()] if match else paragraph
    remainder = paragraph[match.end():].strip() if match else ""

    headline = _clean(first)
    if not _HEADLINE_MIN <= len(headline) <= _HEADLINE_MAX:
        return Lead(body=markdown or "")

    return Lead(headline=headline, standfirst=_clean(remainder), body=rest.strip())


@dataclass(frozen=True)
class KeyFigure:
    """One number the answer turns on, and what it measures."""

    value: str
    label: str


def _percent_move(prior: Any, move: Any) -> str:
    """The movement as a percentage of where it started, or "" when it cannot be."""
    try:
        base = float(prior)
        delta = float(move)
    except (TypeError, ValueError):
        return ""
    if not base:
        return ""
    return f"{delta / abs(base) * 100.0:+.0f}%"


def _measure_label(contribution: Dict[str, Any]) -> str:
    measure = str(contribution.get("measure") or "Total").replace("_", " ").strip()
    return measure[:1].upper() + measure[1:] if measure else "Total"


def key_figures(contribution: Optional[Dict[str, Any]]) -> List[KeyFigure]:
    """The one or two figures a decomposition already establishes.

    Both are read straight off the same totals the drivers panel prints, so the
    headline row and the evidence under it can never disagree.
    """
    payload = contribution or {}
    if not payload.get("drivers"):
        return []

    current = payload.get("current_total")
    if current is None:
        return []

    period = str(payload.get("current_period") or "").strip()
    measure = _measure_label(payload)
    figures = [
        KeyFigure(
            value=format_money(current),
            label=f"{measure} ({period})" if period else measure,
        )
    ]

    percent = _percent_move(payload.get("prior_total"), payload.get("total_move"))
    prior = str(payload.get("prior_period") or "").strip()
    if percent:
        figures.append(
            KeyFigure(value=percent, label=f"Change vs {prior}" if prior else "Change")
        )
    return figures
