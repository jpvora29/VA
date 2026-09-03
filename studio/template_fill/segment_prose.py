"""How one segment finding is SAID — the sentences the industry evidence composes into.

Separate from :mod:`studio.template_fill.feedback` because it has one job and a hard
contract: every figure a sentence here prints must also appear in the ``rendered`` value
:mod:`studio.template_fill.commentary_evidence` built for the same finding, or
``commentary_verify.check_numbers`` drops the line as an unsupported number. Both sides
therefore use the same formatters (:func:`render._money`, ``f"{x:.1f}%"``,
:mod:`studio.template_fill.units`), and a test asserts the containment rather than trusting
the convention.

Two rules shape the wording, and both are enforced elsewhere by gates that would silently
send a whole column back to its draft:

* **Never open on a measure.** ``commentary_metrics.is_restatement`` refuses a bullet that
  opens on "Share"/"Rank"/"Premium" and then neither explains nor concludes — and
  ``commentary._accept`` throws away any rewrite containing one. So the decline sentence is
  "The book gave back 1.4 percentage points…", never "Share fell 1.4…".
* **Diagnose, do not instruct.** These sentences fill What's working / What's not / Growth
  Opportunities, which state position and mechanism. The imperative belongs in Key Messages
  and Priorities, and only tied to a named segment and a figure.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Set

from studio.segments import OPPORTUNITY_KINDS, Placement, SegmentFinding, SegmentFindings
from studio.template_fill import units as U
from studio.template_fill.render import _money


# Two rules pull against each other here, and both are real.
#
# A sentence that states a position and stops is a measurement, not a finding: the half that
# earns its place on a slide is what FOLLOWS from the figure. But the same consequence
# clause repeated on every page is decoration - the deck once closed eleven of its bullets
# with the same eight words, which is the texture that reads as machine-written however
# true each sentence is.
#
# So every variant below carries a consequence, and the variants differ in WHAT the
# consequence is, chosen from what happens to be true of that row. Dropping the "so what"
# to gain variety measured worse on ``commentary_metrics.implication_rate`` and was the
# wrong trade; two different consequences beat one repeated and beat none.


def _peer_clause(row: SegmentFinding) -> str:
    """Where the row sits against the aggregate benchmark, when that is worth saying."""
    if row.peer_sow is None or row.sow is None:
        return ""
    if row.sow >= row.peer_sow + 1.0:
        return f" and ahead of the top-5 peer average of {row.peer_sow:.1f}%"
    if row.peer_sow >= row.sow + 1.0:
        return f" while the top five hold {row.peer_sow:.1f}% of it"
    return ""


def _absent(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    """The gap stated as placement, never as an opportunity.

    ``terms.yaml`` bans qualifying whitespace as addressable without appetite evidence, so
    the sentence says what Marsh placed, what the book wrote, and stops there.
    """
    if row.peer_sow:
        return (f"Marsh placed {_money(row.market)} of premium in {row.name} here and the "
                f"book wrote none of it, while the top five each placed "
                f"{row.peer_sow:.1f}%, so the class is being written by others rather "
                f"than left unplaced.")
    return (f"Marsh placed {_money(row.market)} of premium in {row.name} here and the book "
            f"wrote none of it, so the whole pool sits with other carriers.")


def _thin(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    """The shortfall against the book's own standard, and what it is worth.

    The second one drops the restated benchmark: by then the reader has it, and repeating
    it is what turns two findings into one sentence said twice.
    """
    if lead:
        return (f"{row.name} is a {_money(row.market)} pool where the book holds "
                f"{row.sow:.1f}% of the wallet against the {row.placed_sow:.1f}% it "
                f"averages where it writes, so about {_money(row.stake)} of premium is on "
                f"the table at its own standard.")
    behind = (f" while the top five hold {row.peer_sow:.1f}% of it"
              if (row.peer_sow is not None and row.sow is not None
                  and row.peer_sow >= row.sow + 1.0) else "")
    return (f"It is thin in {row.name} too, {row.sow:.1f}% of a {_money(row.market)} "
            f"pool{behind}, worth about {_money(row.stake)} at the same standard.")


def _behind(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    if lead:
        return (f"In {row.name} the book holds {row.sow:.1f}% of a {_money(row.market)} "
                f"pool against a top-5 peer average of {row.peer_sow:.1f}%, which leaves "
                f"it about {_money(row.stake)} of premium behind carriers writing the same "
                f"class.")
    return (f"{row.name} sits behind the same benchmark, {row.sow:.1f}% against "
            f"{row.peer_sow:.1f}%, which means about {_money(row.stake)} of premium.")


def _strong_tail(row: SegmentFinding, lead: bool) -> str:
    """What this position proves - a different reading for each thing that is true of it.

    The superlative belongs to the lead row only: a runner-up that also called itself the
    deepest placement would contradict the line above it.
    """
    if row.peer_sow is not None and row.sow is not None and row.sow >= row.peer_sow + 1.0:
        return (f", and ahead of the top-5 peer average of {row.peer_sow:.1f}%, so the "
                f"position holds against the benchmark and not just its own history")
    if row.placed_sow and row.sow and row.sow >= row.placed_sow * 1.5:
        return (", half again the rate it manages elsewhere, so the ceiling is higher than "
                "the book's own average suggests")
    if lead:
        return ", so the standard the rest of the book is held to is set here"
    return ", so more than one class supports a deeper position than the average"


def _strong(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    """Only the first one may claim the superlative: two "places best" lines in one column
    is a contradiction the reader notices before anything else on the page."""
    opening = (f"{row.name} is where this book places best, at" if lead
               else f"{row.name} also sits above the book's own standard, at")
    return (f"{opening} {row.sow:.1f}% of a {_money(row.market)} pool against the "
            f"{row.placed_sow:.1f}% it averages where it writes{_strong_tail(row, lead)}.")


def _moved(pct: float) -> str:
    return f"grew {pct:.1f}%" if pct >= 0 else f"fell {abs(pct):.1f}%"


# Share given back while the pool grew this fast is a capture failure rather than a market
# one, and worth saying so. Below it the two are hard to tell apart from premium alone.
_POOL_GREW_CLEARLY = 5.0


def _losing_tail(row: SegmentFinding) -> str:
    moved = row.market_yoy
    if moved is None:
        return ", so the ground went to other carriers"
    if moved < 0:
        return ", so some of that was the pool contracting rather than ground lost"
    if moved >= _POOL_GREW_CLEARLY:
        return ", so this was ground lost rather than a market that shrank"
    return ", so the ground went to other carriers rather than to a shrinking market"


def _losing(row: SegmentFinding, subject: str, lead: bool = False) -> str:
    """Opens on the book, not on "Share": ``commentary_metrics.is_restatement`` refuses a
    bullet that opens on a measure, and ``_accept`` then discards the whole rewrite."""
    moved = (f" that {_moved(row.market_yoy)}" if row.market_yoy is not None else "")
    return (f"The book gave back {U.points(row.sow_delta)} of share in {row.name}, to "
            f"{row.sow:.1f}% of a {_money(row.market)} pool{moved}{_losing_tail(row)}.")


_SENTENCE: Dict[Placement, Callable[[SegmentFinding, str], str]] = {
    Placement.ABSENT: _absent,
    Placement.THIN: _thin,
    Placement.BEHIND: _behind,
    Placement.STRONG: _strong,
    Placement.LOSING: _losing,
}


def sentence(row: SegmentFinding, subject: str = "", lead: bool = False) -> Optional[str]:
    """One finding as a diagnostic sentence, or ``None`` for a class that says nothing.

    ``lead`` marks the first finding of its class in a column, which is the only one
    allowed to claim a superlative.
    """
    build = _SENTENCE.get(row.placement)
    return build(row, subject, lead) if build else None


def _ordered(found: Dict[str, SegmentFindings], kinds: Sequence[Placement],
             ) -> List[SegmentFinding]:
    """Findings of these kinds across every dimension, most premium at stake first.

    Kept in one ranking rather than one per dimension so an industry worth $30M and a client
    segment worth $12M compete on the figure, which is the whole point of ``stake``.
    """
    rows: List[SegmentFinding] = []
    for findings in found.values():
        rows.extend(findings.of(*kinds))
    return sorted(rows, key=lambda r: r.stake, reverse=True)


def points(found: Dict[str, SegmentFindings], *kinds: Placement, subject: str = "",
           limit: int = 3, per_dim: int = 2) -> List[str]:
    """The ranked findings of these kinds as sentences, covering each kind before repeating.

    Ranking on ``stake`` alone lets the richest kind take every slot: a line absent from
    three industries would spend the whole column saying so and never reach the one it
    writes below its own standard. So the first pass takes the strongest finding of EACH
    kind, in the order the kinds argue, and only then fills what is left by premium. A
    column that names an absence, an under-penetration and a peer gap tells a reader three
    different things; one that names three absences tells them one.

    ``per_dim`` stops a single dimension filling the column, so a scope with five absent
    industries still says something about its client segments.
    """
    wanted = tuple(kinds) or OPPORTUNITY_KINDS
    ordered = _ordered(found, wanted)

    first = [next((r for r in ordered if r.placement is kind), None) for kind in wanted]
    rest = [r for r in ordered if r not in first]

    out: List[str] = []
    taken: Dict[str, int] = {}
    led: Set[Placement] = set()
    for row in [r for r in first if r is not None] + rest:
        if len(out) >= limit:
            break
        if taken.get(row.dim, 0) >= per_dim:
            continue
        line = sentence(row, subject, lead=row.placement not in led)
        if not line:
            continue
        led.add(row.placement)
        taken[row.dim] = taken.get(row.dim, 0) + 1
        out.append(line)
    return out


def absence_summary(found: Dict[str, SegmentFindings], subject: str = "") -> Optional[str]:
    """Several absent segments compressed into one line, when naming them all would not fit.

    A scope absent from six industries has one finding, not six, and a column that lists
    them individually spends every bullet on the same point.
    """
    for findings in found.values():
        rows = findings.of(Placement.ABSENT)
        if len(rows) < 2:
            continue
        named = ", ".join(r.name for r in rows[:2])
        rest = len(rows) - 2
        tail = f" and {rest} other {findings.label}" + ("s" if rest != 1 else "") if rest else ""
        return (f"Across {len(rows)} {findings.label} groups the book writes nothing at all, "
                f"{named}{tail}, together worth {_money(findings.absent_total)} of Marsh "
                f"placements.")
    return None


def tracking_note(label: str = "industry", share: Optional[float] = None) -> str:
    """What a scope that matches its parent says instead of inventing a difference.

    Worth a line: it tells a leadership team there is no local anomaly to chase, which is
    a finding. Manufacturing a difference to fill the column is what the deck did before.
    """
    at = f", and at {share:.1f}% of the wallet" if share is not None else ", so"
    return (f"The book's {label} mix here tracks the wider portfolio closely{at} nothing "
            f"in this scope behaves differently from the group.")
