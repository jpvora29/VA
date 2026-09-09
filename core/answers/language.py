"""The two bits of English that more than one answer module needs.

Both `core.answers.steps` (describing a query) and `core.answers.shape` (writing
a drivers lead) have to say "a, b and c" and turn "product line" into "product
lines". Neither is a natural home for the other's copy, and two implementations
of pluralisation drift the moment one of them meets a word ending in "y".

Deliberately small. This is not a utils module; if a third kind of helper wants
to live here, it probably wants its own file instead.
"""
from __future__ import annotations

from typing import Sequence


def join_words(parts: Sequence[str]) -> str:
    """A list as a person writes it — "a", "a and b", "a, b and c"."""
    items = [str(p) for p in parts if p]
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


def plural(noun: str, count: int = 2) -> str:
    """Enough pluralisation for the nouns a column name produces.

    Column names are short noun phrases — "product line", "country", "industry"
    — so the two English rules that matter are the bare "s" and the "y" that
    becomes "ies" after a consonant. Anything more would be a library.
    """
    word = str(noun or "").strip()
    if count == 1 or not word or word.endswith("s"):
        return word
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def count_of(count: int, noun: str) -> str:
    """"1 product line", "9 product lines"."""
    return f"{count:,} {plural(noun, count)}"
