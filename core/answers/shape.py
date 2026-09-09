"""What KIND of movement this is — so two different results do not read alike.

The drivers panel drew the same ranked bars whatever it was given. That is fine
once and mundane by the fourth time, and worse than mundane: it hides the finding
behind a shape the reader has to re-derive every visit. A decline carried by two
countries and a decline spread evenly across eleven product lines are different
findings, and they should not look the same.

So the decomposition is classified first, from arithmetic on the deltas, and the
panel leads with the sentence and the picture that fit:

    single        one slice is nearly the whole movement
    concentrated  a handful of slices carry most of it
    offsetting    big movement both ways that nearly cancels out
    broad         almost everything moved the same way, none of it dominant
    mixed         none of the above cleanly; the ranked bars are the honest read
    flat          nothing moved

The vocabulary the classification is built on is **gross** and **net**. Gross is
how much movement there was (the sum of the absolute deltas); net is what the
total actually did. `offsetting` is precisely the case where gross is large and
net is small, and it is the one the old panel told worst — "premium was flat" is
not the finding when $3.1m of falls cancelled $2.9m of growth.

Every threshold below is a judgement, so each is named and carries the reason it
is where it is. Pure: a `Contribution` in, a `Profile` out.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from core.answers.contribution import Contribution, Driver
from core.answers.language import join_words, plural

SINGLE = "single"
CONCENTRATED = "concentrated"
OFFSETTING = "offsetting"
BROAD = "broad"
MIXED = "mixed"
FLAT = "flat"

# ── the thresholds, and why each is where it is ──────────────────────────────

# `offsetting` needs the net to be SMALL against the gross. At 0.30 a total that
# moved a third of what its parts moved still reads as a real net movement; below
# that, "the total barely moved" is the truer sentence.
_NET_IS_SMALL = 0.30

# …and it needs both directions to be substantial. Without this, one big fall and
# one trivial rise would qualify whenever the fall happened to be small.
_BOTH_WAYS_MATTER = 0.25

# One slice being 60% of everything that moved makes it the story on its own.
_SINGLE_SHARE = 0.60

# Two or three slices carrying 70% is "a handful account for most of it".
_CONCENTRATED_SHARE = 0.70
_CONCENTRATED_MAX_SLICES = 3

# `broad` is about the ABSENCE of a leader: most slices moving the same way, and
# none of them dominant. Below five slices "most of them" is not a finding.
_BROAD_MIN_SLICES = 5
_BROAD_AGREEMENT = 0.60
_BROAD_NO_LEADER = 0.40


@dataclass(frozen=True)
class Profile:
    """The shape of a movement, and the sentence that states it.

    `leaders` are the slices the lead sentence is about, so the panel can
    highlight exactly those rows rather than guessing from the ranking again.
    """

    shape: str = MIXED
    lead: str = ""
    leaders: Tuple[str, ...] = field(default_factory=tuple)
    gained: float = 0.0
    lost: float = 0.0
    net: float = 0.0
    gross: float = 0.0
    covered_pct: float = 0.0
    moved_with: int = 0
    moved_against: int = 0
    total_slices: int = 0

    def as_dict(self) -> dict:
        return {
            "shape": self.shape,
            "lead": self.lead,
            "leaders": list(self.leaders),
            "gained": self.gained,
            "lost": self.lost,
            "net": self.net,
            "gross": self.gross,
            "covered_pct": self.covered_pct,
            "moved_with": self.moved_with,
            "moved_against": self.moved_against,
            "total_slices": self.total_slices,
        }


def _money(amount: float) -> str:
    """Deferred import: the formatter reads a config file, and `shape` is pure."""
    from core.boardroom.money import format_money

    return format_money(abs(amount))


def _verb(delta: float, *, past: bool = True) -> str:
    if past:
        return "fell" if delta < 0 else "grew"
    return "fall" if delta < 0 else "rise"


def _noun(contribution: Contribution) -> str:
    """"product line" — the slice, lowercase, for use inside a sentence."""
    return str(contribution.dimension or "slice").replace("_", " ").strip().lower()


def _gross(movers: Sequence[Driver]) -> float:
    return sum(abs(d.delta) for d in movers)


def _leaders_covering(movers: Sequence[Driver], gross: float, target: float) -> List[Driver]:
    """The fewest top slices whose movement reaches `target` of the gross."""
    if not gross:
        return []
    running, out = 0.0, []
    for driver in movers:
        out.append(driver)
        running += abs(driver.delta)
        if running / gross >= target:
            break
    return out


def _offsetting_lead(contribution: Contribution, gained: float, lost: float) -> str:
    """The case the old panel told worst: flat on top, violent underneath."""
    measure = str(contribution.measure or "the measure").replace("_", " ").lower()
    return (
        f"Overall {measure} barely moved — but {_money(lost)} of falls almost "
        f"cancelled out {_money(gained)} of growth. The net is quiet; the book is not."
    )


def _single_lead(contribution: Contribution, lead: Driver, share: float) -> str:
    sentence = (
        f"{lead.name} is {share:.0f}% of everything that moved: it "
        f"{_verb(lead.delta)} {_money(lead.delta)}."
    )
    offsets = contribution.against
    if offsets:
        sentence += f" {join_words([d.name for d in offsets[:2]])} moved the other way."
    return sentence


# "Two product lines" reads as a finding; "2 product lines" reads as a field.
# Only the counts `concentrated` can produce are needed.
_WORDS = {1: "One", 2: "Two", 3: "Three"}


def _concentrated_lead(contribution: Contribution, leaders: Sequence[Driver], share: float) -> str:
    count = len(leaders)
    noun = plural(_noun(contribution), count)
    named = join_words(
        [f"{d.name} ({'-' if d.delta < 0 else '+'}{_money(d.delta)})" for d in leaders]
    )
    return (
        f"{_WORDS.get(count, str(count))} {noun} account for {share:.0f}% "
        f"of the movement: {named}."
    )


def _broad_lead(contribution: Contribution, with_move: int, total: int) -> str:
    noun = plural(_noun(contribution), total)
    direction = _verb(contribution.total_move, past=False)
    return (
        f"The {direction} is broad, not concentrated: {with_move} of {total} {noun} "
        f"moved the same way, and none of them carries it."
    )


def _mixed_lead(contribution: Contribution) -> str:
    """No clean pattern — the ranked bars are the honest read, so say that."""
    return contribution.headline()


def classify(contribution: Contribution) -> Profile:
    """The shape of this movement, and the sentence that leads with it."""
    movers = contribution.movers
    net = contribution.total_move
    if not movers:
        return Profile(shape=FLAT, lead="Nothing moved between these periods.")

    gained = sum(d.delta for d in movers if d.delta > 0)
    lost = sum(d.delta for d in movers if d.delta < 0)
    gross = _gross(movers)
    with_move = len([d for d in movers if (d.delta > 0) == (net > 0)]) if net else 0
    against = len(movers) - with_move
    base = dict(
        gained=gained, lost=lost, net=net, gross=gross,
        moved_with=with_move, moved_against=against, total_slices=len(movers),
    )

    # Order matters: `offsetting` is checked first because a near-cancelling pair
    # would otherwise be reported as `single` on whichever side is larger, which
    # is true but is not the finding.
    both_ways = min(gained, abs(lost)) >= _BOTH_WAYS_MATTER * gross
    if gross and abs(net) <= _NET_IS_SMALL * gross and both_ways:
        return Profile(
            shape=OFFSETTING,
            lead=_offsetting_lead(contribution, gained, lost),
            leaders=tuple(d.name for d in movers[:2]),
            covered_pct=round(min(gained, abs(lost)) / gross * 100, 1),
            **base,
        )

    top = movers[0]
    top_share = round(abs(top.delta) / gross * 100, 1) if gross else 0.0
    if top_share >= _SINGLE_SHARE * 100:
        return Profile(
            shape=SINGLE,
            lead=_single_lead(contribution, top, top_share),
            leaders=(top.name,),
            covered_pct=top_share,
            **base,
        )

    leaders = _leaders_covering(movers, gross, _CONCENTRATED_SHARE)
    if leaders and len(leaders) <= _CONCENTRATED_MAX_SLICES and len(movers) > len(leaders):
        # Rounded ONCE, here, and both the sentence and the panel's key read that
        # one number. Formatting the raw float in one place and the 1dp value in
        # the other put "93%" in the lead above a bar labelled "94%".
        covered = round(sum(abs(d.delta) for d in leaders) / gross * 100, 1)
        return Profile(
            shape=CONCENTRATED,
            lead=_concentrated_lead(contribution, leaders, covered),
            leaders=tuple(d.name for d in leaders),
            covered_pct=covered,
            **base,
        )

    if (
        len(movers) >= _BROAD_MIN_SLICES
        and with_move >= _BROAD_AGREEMENT * len(movers)
        and top_share < _BROAD_NO_LEADER * 100
    ):
        return Profile(
            shape=BROAD,
            lead=_broad_lead(contribution, with_move, len(movers)),
            leaders=tuple(d.name for d in movers[:3]),
            covered_pct=round(with_move / len(movers) * 100, 1),
            **base,
        )

    return Profile(
        shape=MIXED,
        lead=_mixed_lead(contribution),
        leaders=(top.name,),
        covered_pct=top_share,
        **base,
    )
