"""The opportunity evidence ladder — what premium data may and may not call an opportunity.

Premium data shows one thing about a gap: somebody else wrote it. That is not the same as
the carrier being able to write it, and the difference is the whole distance between an
observation and a plan. Collapsing it — "market premium" becoming "addressable market",
"placed elsewhere" becoming "headroom" — is what makes a QBR recommend entering a line
nobody has checked the appetite for.

Three rungs, and the evidence each one needs:

    observed      premium exists in the pool and the carrier writes little or none of it
                  — a PREMIUM fact, and the only rung premium data can reach on its own
    addressable   + the line fits stated appetite and available capacity
    validated     + target clients, broker access, economics and an execution path

The recommended verb keys off the rung, so the deck cannot say "enter" from an observation:
an observed gap earns "validate appetite and capacity", and nothing stronger, until an input
this warehouse does not hold says otherwise. That is a deliberate ceiling, not a limitation
to route around — see :mod:`studio.posture`, whose ``Validate`` stance is this same rung.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Evidence(str, Enum):
    OBSERVED = "observed"
    ADDRESSABLE = "addressable"
    VALIDATED = "validated"


# Rung → the action it earns. The verbs are the posture vocabulary's own, so a deck says
# the same word for the same idea wherever it appears.
_ACTION = {
    Evidence.OBSERVED: "Validate",
    Evidence.ADDRESSABLE: "Selectively pursue",
    Evidence.VALIDATED: "Enter",
}

# What each rung is still missing, said plainly. The observed rung names the two inputs a
# premium warehouse does not hold, which is the honest reason the deck cannot go further.
_MISSING = {
    Evidence.OBSERVED: "appetite and capacity are unconfirmed",
    Evidence.ADDRESSABLE: "target clients, broker access and economics are unconfirmed",
    Evidence.VALIDATED: "",
}


@dataclass(frozen=True)
class Opportunity:
    """A gap, its size, and how far up the ladder the evidence actually reaches."""

    name: str
    pool: float                                  # Marsh premium placed in the gap
    written: float = 0.0                         # what the carrier writes of it
    level: Evidence = Evidence.OBSERVED

    @property
    def unwritten(self) -> float:
        return max(self.pool - self.written, 0.0)


def level_from_premium_only() -> Evidence:
    """The highest rung premium data alone can reach.

    A named function rather than a bare constant at the call sites: every caller reading
    only the premium warehouse goes through here, so the day an appetite or capacity input
    arrives there is one place that has to change.
    """
    return Evidence.OBSERVED


def action_for(level: Evidence) -> str:
    """The verb this rung earns — never a stronger one."""
    return _ACTION[level]


def qualifier_for(level: Evidence) -> str:
    """What is still unconfirmed at this rung (empty at the top)."""
    return _MISSING[level]


def describe(opp: Opportunity, *, money) -> str:
    """The gap stated as what it IS — a pool someone else writes, not a market to be had.

    ``money`` is the caller's own formatter, so the sentence carries the same currency
    styling as the page around it.
    """
    written = ("" if opp.written <= 0
               else f", of which the carrier writes {money(opp.written)}")
    return (f"{opp.name} is a {money(opp.pool)} Marsh pool placed with other "
            f"carriers{written}.")


def recommend(opp: Opportunity, *, money) -> str:
    """The action the evidence earns, with the reason it is not a stronger one."""
    verb = action_for(opp.level)
    missing = qualifier_for(opp.level)
    tail = f" — {missing}" if missing else ""
    return (f"{verb} {opp.name}: {money(opp.unwritten)} of Marsh premium sits with other "
            f"carriers{tail}.")
