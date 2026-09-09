"""What each data source is called, in business words.

A "lens" is the product's internal name for a body of data — `premium`, `gpr`,
`survey`, `gimmi`. None of those belong on screen, and the reader meets the same
source in two places on the same card: as the tab over the evidence table, and as
the first step of "How this was calculated". Naming it twice is how a tab reading
"Premium" ends up above steps reading "Read the gpr fact data".

So the vocabulary lives here, once, and both surfaces read it:

    label        the short name, for a tab or a heading   "Premium"
    description  the phrase a sentence uses               "the Marsh-placed premium records"

Pure data and two lookups. An unmapped lens returns nothing rather than a guess —
the caller decides what to fall back to, because the honest fallback differs
(a tab falls back to its position, a step to the humanised table name).
"""
from __future__ import annotations

from typing import Dict

# The short name. Used as an evidence tab and, with "data" after it, as the
# heading over a block of calculation steps.
LABELS: Dict[str, str] = {
    "premium": "Premium",
    "gpr": "Premium",
    "survey": "Broker survey",
    "gimmi": "GIMMI",
    "combined": "Combined",
}

# The phrase that reads well inside a sentence — "Started with ...".
DESCRIPTIONS: Dict[str, str] = {
    "premium": "the Marsh-placed premium records",
    "gpr": "the Marsh-placed premium records",
    "survey": "the broker survey responses",
    "gimmi": "the GIMMI market sizing data",
    "combined": "the combined data",
}


def _key(lens: str) -> str:
    return str(lens or "").strip().lower()


def label_of(lens: str) -> str:
    """The short name, or "" when the lens is not one we have a word for."""
    return LABELS.get(_key(lens), "")


def description_of(lens: str) -> str:
    """The in-sentence phrase, or "" when the lens is not one we have a word for."""
    return DESCRIPTIONS.get(_key(lens), "")
