"""Who and when a sentence is about — checked against the evidence it came from.

The narration gate proves every FIGURE came from the ledger. It cannot see a
figure moved onto the wrong subject: "AIG premium in Singapore was $1.5M in
2024", written from CHUBB evidence, carries a real number and passes. This
module catches the two cheapest ways a true number becomes a false sentence:

* a carrier or country the evidence never mentions;
* a year the evidence never mentions.

Deterministic and pure. The vocabulary is the warehouse's own valid values; a
name only counts when it is written as a name (capitalised, or in capitals for
a short acronym), and carrier names that are ordinary English words ("Dual",
"Axis", "Liberty") are left out, because a check that fires on prose is worse
than one that misses a rare case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

#: Carrier names that are also everyday words in an analyst's prose. Matching
#: them would drop correct sentences ("a dual focus", "on the axis").
AMBIGUOUS_NAMES = frozenset({
    "aegis", "amp", "arch", "ascot", "aspen", "axis", "continental", "dual",
    "ergo", "fusion", "gard", "geo", "hamilton", "hanover", "liberty", "liva",
    "luma", "mosaic", "nexus", "not defined", "orion", "pioneer", "protector",
    "sentry",
})

#: Words that say what kind of company a name is, not which one.
_GENERIC = frozenset({
    "the", "insurance", "group", "company", "co", "ltd", "limited", "inc",
    "plc", "berhad", "reinsurance", "retail", "wholesale", "general",
    "new", "south", "north", "united",
})

_YEAR = re.compile(r"\b(20\d\d)\b")
_ACRONYM_MAX = 3


@dataclass(frozen=True)
class SubjectCheck:
    """What one answer may name, built once from its brief."""

    pattern: "re.Pattern[str] | None"
    allowed_words: frozenset[str]
    allowed_years: frozenset[str]

    def unsupported(self, sentence: str) -> list[str]:
        """The names and years in `sentence` the evidence does not mention."""
        return [*self._names(sentence), *self._years(sentence)]

    def _names(self, sentence: str) -> list[str]:
        if self.pattern is None:
            return []
        return [m.group(0) for m in self.pattern.finditer(sentence)
                if _written_as_name(m.group(0))
                and _key_word(m.group(0)) not in self.allowed_words]

    def _years(self, sentence: str) -> list[str]:
        if not self.allowed_years:
            return []
        return [y for y in _YEAR.findall(sentence) if y not in self.allowed_years]


def build_subject_check(vocabulary: Iterable[str], allowed_texts: Iterable[str]) -> SubjectCheck:
    """A check for one answer: `vocabulary` is every known name, `allowed_texts`
    everything the answer was built from (question, scope, facts, claims)."""
    texts = [str(t) for t in allowed_texts if t not in (None, "")]
    return SubjectCheck(
        pattern=_pattern(tuple(sorted(_usable(vocabulary), key=len, reverse=True))),
        allowed_words=frozenset(w for t in texts for w in _words(t)),
        allowed_years=frozenset(y for t in texts for y in _YEAR.findall(t)),
    )


def allowed_texts_of(question: str, scope: Sequence, facts: Sequence, claims: Sequence,
                     defaulted_period: str = "") -> list[str]:
    """Every piece of text an answer is entitled to name things from."""
    texts = [question, defaulted_period]
    texts += [str(v) for _, v in scope]
    for fact in facts:
        texts += [str(v) for _, v in getattr(fact, "dimensions", ())]
        texts.append(getattr(fact, "rendered", ""))
    texts += [getattr(c, "text", "") for c in claims]
    return texts


@lru_cache(maxsize=1)
def warehouse_vocabulary() -> frozenset[str]:
    """Carrier and country names from the warehouse's valid values."""
    try:
        from config import valid_values_config as values
    except Exception:  # noqa: BLE001 - no vocabulary means no name check, never a crash
        return frozenset()
    names: set[str] = set()
    for attr in ("valid_carriers", "valid_groups_gpr", "valid_countries", "valid_countries_gpr"):
        names |= {str(n).strip() for n in getattr(values, attr, ()) or ()}
    return frozenset(n for n in names if n)


def _usable(vocabulary: Iterable[str]) -> list[str]:
    return [n for n in {str(v).strip() for v in vocabulary}
            if n and n.lower() not in AMBIGUOUS_NAMES and _key_word(n)]


def _pattern(names: Sequence[str]) -> "re.Pattern[str] | None":
    if not names:
        return None
    body = "|".join(re.escape(n) for n in names)
    return re.compile(rf"(?<![\w&])(?:{body})(?![\w&])", re.IGNORECASE)


def _written_as_name(token: str) -> bool:
    """Short acronyms only in capitals ("AIG", not "aig"); others capitalised."""
    if len(token) <= _ACRONYM_MAX:
        return token.isupper()
    return token[:1].isupper()


def _key_word(name: str) -> str:
    """The word that identifies a name: 'AIG' in 'AIG GROUP', 'chubb' in 'Chubb Ltd'."""
    for word in _words(name):
        if word not in _GENERIC:
            return word
    return ""


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9&]+", text.lower())
