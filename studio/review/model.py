"""What a Review says, as data — no Dash, no formatting policy, no IO.

The Review tab used to list validation errors: true, but not useful. What an author
actually needs to know before they send a deck is *which boxes are still the template's
own placeholder, and why* — and "why" is almost never about that box. Ten blank cells on
four slides are usually one fact about the data (there is no prior year in scope), so the
report is built around CAUSES with their slots attached, not around slots with a message
each.

Four dataclasses carry that:

  :class:`Cause`             one reason things are blank: the mechanism and the fix.
  :class:`Capability`        one thing the run's data can or cannot support.
  :class:`SlotFinding`       one placeholder that did not fill, and the cause it belongs to.
  :class:`CommentaryFinding` one prose box, and whether it got written.

:class:`ReviewReport` holds all of them plus the grouping the page renders from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Cause:
    """One reason a set of slots is unfilled, in the author's terms.

    ``why`` states the mechanism — what the fill engine tried and what stopped it — and
    ``fix`` says what the author can change. A cause with no ``fix`` is one nothing on
    this screen can resolve, and says so.
    """

    id: str
    title: str
    why: str
    fix: str = ""
    severity: str = "warn"          # "warn" (honest gap) | "error" (should not happen)


@dataclass(frozen=True)
class Capability:
    """One thing the data in scope can or cannot support, and what rides on it."""

    id: str
    label: str
    available: bool
    detail: str                      # what it means, either way
    roles: Tuple[str, ...] = ()      # the roles it feeds when available
    cause_id: str = ""               # the cause its absence creates

    #: Set on the root capability (a reporting year) — without it nothing resolves at
    #: all, so it owns every unfilled data slot rather than only its own roles.
    owns_everything: bool = False


@dataclass(frozen=True)
class SlotFinding:
    """One placeholder that did not fill, and why."""

    slot_key: str
    slide_no: int                    # 1-based, the number the author sees
    role: Optional[str]
    token: str
    context: str
    value_kind: str
    cause_id: str


@dataclass(frozen=True)
class CommentaryFinding:
    """One prose box on a commentary page, and what it ended up carrying."""

    slot_key: str
    slide_no: int
    lines: int
    filled: bool
    cause_id: str = ""


@dataclass(frozen=True)
class CauseGroup:
    """A cause with the findings it explains — what one row of the report shows."""

    cause: Cause
    findings: Tuple[SlotFinding, ...]

    @property
    def count(self) -> int:
        return len(self.findings)

    def slides(self) -> Tuple[int, ...]:
        """The pages this cause shows up on, in order and without repeats."""
        return tuple(sorted({f.slide_no for f in self.findings}))


#: Studio holds two documents and Review reads them differently. ``TEMPLATE`` is the
#: editable plan — a manifest of every slot and what it resolved to, so coverage is a
#: meaningful percentage. ``ASSEMBLED`` is the merged ``.pptx`` the author is about to
#: send, where nothing is a plan any more and the question is what is still a
#: placeholder in the file (:mod:`studio.review.assembled`).
TEMPLATE = "template"
ASSEMBLED = "assembled"


@dataclass(frozen=True)
class ReviewReport:
    """Everything the Review tab needs, computed from the document on screen."""

    source: str = TEMPLATE
    subject: str = ""
    period_year: Optional[int] = None
    slides_total: int = 0
    slides_hidden: int = 0
    slots_total: int = 0
    slots_filled: int = 0
    capabilities: Tuple[Capability, ...] = ()
    groups: Tuple[CauseGroup, ...] = ()
    commentary: Tuple[CommentaryFinding, ...] = ()

    @property
    def slots_open(self) -> int:
        return sum(g.count for g in self.groups)

    @property
    def clean(self) -> bool:
        return not self.groups

    def errors(self) -> Tuple[CauseGroup, ...]:
        """Groups that should never happen — a bug or an edit to undo, not a data gap."""
        return tuple(g for g in self.groups if g.cause.severity == "error")

    def gaps(self) -> Tuple[CauseGroup, ...]:
        """Groups that are honest consequences of the data in scope."""
        return tuple(g for g in self.groups if g.cause.severity != "error")

    def missing_capabilities(self) -> Tuple[Capability, ...]:
        return tuple(c for c in self.capabilities if not c.available)

    def blocking_capabilities(self) -> Tuple[Capability, ...]:
        """Missing capabilities that actually cost THIS deck something.

        Most templates ask for a subset of the vocabulary, so a run with no survey book
        is only a gap on a deck that has a survey tile. Reporting every absence would
        make a finished deck look broken, so a capability counts as a gap only once a
        slot on a shipped page is blank because of it.
        """
        blamed = {g.cause.id for g in self.groups}
        return tuple(c for c in self.missing_capabilities() if c.cause_id in blamed)

    def commentary_written(self) -> int:
        return sum(1 for c in self.commentary if c.filled)

    @property
    def measures_coverage(self) -> bool:
        """Whether a "% filled" means anything for this document — see :data:`TEMPLATE`."""
        return self.source == TEMPLATE

    def coverage_pct(self) -> int:
        """How much of the mapped template actually carries this deck's data."""
        if not self.slots_total:
            return 0
        return round(100 * self.slots_filled / self.slots_total)


__all__ = [
    "Cause", "Capability", "SlotFinding", "CommentaryFinding", "CauseGroup", "ReviewReport",
    "TEMPLATE", "ASSEMBLED",
]
