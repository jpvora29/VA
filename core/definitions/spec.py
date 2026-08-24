"""One ICG business term, immutable.

Mirrors :mod:`core.registry.spec`: the YAML is the single source of truth, this is the
typed read-only view of it. A :class:`Term` knows four things about a concept — what it
means, how this system computes it, how to say it, and the overstatement it attracts — and
the last of those is the reason the file exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

# What a term's figures are measured in. Drives rendering (percentage points are spelled
# out, currency is not) and nothing else — the glossary describes, it does not compute.
UNITS = frozenset({"currency", "percent", "percentage_points", "rank", "score", ""})


@dataclass(frozen=True)
class Term:
    """A business concept as ICG uses it."""

    key: str
    label: str
    definition: str
    aliases: Tuple[str, ...] = ()
    formula: str = ""
    say: str = ""
    never: str = ""
    unit: str = ""

    @property
    def is_computed(self) -> bool:
        """True when this product derives the term from data.

        ``appetite`` and ``renewal_book`` are not: they are things a carrier or an account
        team knows and the premium book does not. A writer given the glossary must be able
        to tell the two kinds apart, or it will infer the uncomputable ones from premium —
        which is exactly the failure ``never`` describes.
        """
        return bool(self.formula.strip())

    def as_brief(self) -> str:
        """The term as one prompt block — definition, phrasing, and the ban."""
        lines = [f"{self.label} — {self.definition}"]
        if self.formula:
            lines.append(f"  Computed as: {self.formula}")
        else:
            lines.append("  NOT computed from our data.")
        if self.say:
            lines.append(f"  Say: {self.say}")
        if self.never:
            lines.append(f"  NEVER: {self.never}")
        return "\n".join(lines)
