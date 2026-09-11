"""The editorial plan — which field owns which finding, decided before anything is written.

The claim ledger (:mod:`studio.template_fill.ledger`) stops a repeated STRING on the
deterministic draft. It cannot stop what a reader actually complains about, because by the
time the model writes, the same finding has three legitimate wordings:

    "share of wallet sits 1.7pp below the top-5 peer average"
    "the book is about $39M of premium behind peer parity"
    "reaching peer parity means winning 1.7pp of share, worth about $39M"

Three sentences, no repeated string, no repeated number in two of the pairs — and one
finding, printed three times on one slide. That happened because ``peer.gap`` and
``peer.gap_value`` are the SAME fact in two units, and four of the seven columns lead from
the ``peer.`` family (:data:`studio.template_fill.commentary._TOPIC_EVIDENCE`). Every
column was briefed differently, handed the same gap, and each reached for it.

So this module answers the question one layer earlier: **before the deck is written, which
field is the home for each finding?**

    fact ids            ->  a CLAIM TOPIC     (peer.gap and peer.gap_value are one topic)
    a section's columns ->  an allocation     (one owner per topic, spread round-robin)
    the allocation      ->  a brief per field ("yours"; "another field's, in any form")
                        ->  a dedupe gate     (a claim ships once per page)

The allocation is a draft pick, not a filter: every column takes its highest-ranked
unclaimed topic in turn, so a column that loses the peer gap is pointed at the finding it
ranks next rather than left with nothing. That distinction is load-bearing —
:mod:`studio.template_fill.ledger`'s history is that dedupe alone THINS pages, and the fix
was never a looser rule, it was giving the page somewhere else to go.

The gate is a repetition rule, not an ownership rule: a topic only one field claimed ships
wherever it was written, because nothing was repeated. Only the second and later copies are
dropped, and a field the gate empties is sent back to be written on something else rather
than allowed to keep one copy — see :func:`dedupe`.

Pure and deterministic: fact ids and text in, a plan out. No IO, no model, no state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
)

from logger import get_logger

logger = get_logger(__name__)


# ── what a finding IS ────────────────────────────────────────────────────────

#: A claim topic: the finding a sentence makes, independent of the unit it makes it in.
ClaimTopic = str

#: Fact-id prefix -> the topic it belongs to. Ordered, and matched longest-first, so a
#: more specific family wins over the one it sits inside.
#:
#: The collapses are the point of the table. ``peer.gap`` (percentage points),
#: ``peer.gap_value`` (the premium those points are worth) and ``share.point_value`` (what
#: one point costs) are three renderings of one distance to one benchmark; a page that
#: prints two of them has said one thing twice. Same for ``mover.`` and ``pool.``, which
#: are the two halves of a single decomposition — what the carrier did and what the pool
#: it sits in did.
_TOPIC_OF_PREFIX: Tuple[Tuple[str, ClaimTopic], ...] = (
    ("peer.", "peer_gap"),
    ("share.point_value", "peer_gap"),
    ("rank.", "standing"),
    ("sow.", "standing"),
    ("mover.", "movement"),
    ("pool.", "movement"),
    ("trend.", "momentum"),
    ("segment.", "headroom"),
    ("headroom", "headroom"),
    ("mix.", "concentration"),
    ("carrier.", "scale"),
    ("marsh.", "scale"),
)

#: How a topic is named to the writer. Plain English, and it says WHY two forms are one
#: finding — a model told only "peer_gap is taken" still writes the dollar version.
_TOPIC_LABEL: Dict[ClaimTopic, str] = {
    "peer_gap": "the distance to the peer benchmark — in percentage points, in premium, "
                "or as 'reaching parity'; all three are the same finding",
    "standing": "where the carrier stands — rank and share of wallet, and their movement",
    "movement": "what moved the carrier's premium and how the Marsh book moved with it",
    "momentum": "the trajectory — whether the year's move is still running",
    "headroom": "headroom: premium another carrier already writes, and what taking it "
                "would be worth",
    "concentration": "how concentrated the carrier's premium is, and in what",
    "scale": "the size of the carrier's premium and of the Marsh book around it",
}

#: The same topics, named briefly — for the list of what a field may NOT say, which is as
#: long as the page has fields and would otherwise be most of the field's ask. A field
#: needs the full label for the finding it OWNS and only needs to recognise the rest.
#:
#: ``peer_gap`` keeps its units clause in both forms on purpose: that a gap in points and
#: the same gap in premium are one finding is the thing being banned, and a field told
#: only "the peer gap is taken" writes the dollar version.
_TOPIC_SHORT: Dict[ClaimTopic, str] = {
    "peer_gap": "the peer gap, in points OR in premium OR as 'parity'",
    "standing": "rank and share of wallet",
    "movement": "what moved the carrier, and the Marsh book around it",
    "momentum": "the trajectory",
    "headroom": "headroom and what taking it is worth",
    "concentration": "how concentrated the carrier is",
    "scale": "the size of the carrier's premium",
}


def _short(topic: ClaimTopic) -> str:
    return _TOPIC_SHORT.get(topic, _TOPIC_LABEL.get(topic, topic))


#: Text patterns for a topic, for the sentences that cite no fact id and for the
#: whole-deck QA sweep, which sees finished prose and no citations at all.
#: Ordered: the first match wins, so the narrower phrase is tested before the word it
#: contains ("peer parity" before "share of wallet").
_TOPIC_OF_TEXT: Tuple[Tuple[re.Pattern, ClaimTopic], ...] = (
    (re.compile(r"peer (?:average|parity|set)|top-5 peer|behind the peer|to parity", re.I),
     "peer_gap"),
    (re.compile(r"headroom|whitespace|writes nothing|places nothing|additional (?:GWP|"
                r"premium)|would be worth", re.I), "headroom"),
    (re.compile(r"accelerat|slowing|still running|trailing twelve|latest quarter|momentum",
                re.I), "momentum"),
    (re.compile(r"concentrat|largest (?:three|four|five)|rests on", re.I), "concentration"),
    (re.compile(r"\brank(?:ed|s|ing)?\b|share of wallet|#\d+", re.I), "standing"),
    (re.compile(r"\bpool\b|grew faster than|added \$|drove|driven by", re.I), "movement"),
)

#: Words that look like a named driver and name nothing. Two groups, and both are needed.
#:
#: The QBR vocabulary ("Marsh", "GWP", "Share of wallet") is capitalised in every other
#: sentence the deck writes, so without it every claim about the Marsh book carries the
#: driver "Marsh" and two claims about different things look alike.
#:
#: The ordinary sentence openers are needed because the first word IS considered here.
#: Excluding position one instead — the obvious way to skip a sentence-initial "The" —
#: silently drops the driver from every line that leads with it ("Cyber sits 2.0pp below
#: the peer average"), and a line whose driver is dropped is compared as though it were
#: about the whole book, which is how a real per-product finding gets called a repeat.
_GENERIC_ENTITIES = frozenset({
    "marsh", "gwp", "sow", "qbr", "icg", "share", "rank", "premium", "parity",
    "momentum", "growth", "book", "headroom", "whitespace",
    "the", "a", "an", "at", "in", "on", "by", "for", "with", "within", "across",
    "this", "that", "these", "those", "it", "there", "both", "neither", "every",
    "writing", "reaching", "closing", "winning", "holding", "defending", "taking",
    "where", "what", "when", "while", "against", "over", "under", "most", "much",
})

#: A capitalised name — the product, country or industry a claim is about. Anywhere in the
#: sentence, with :data:`_GENERIC_ENTITIES` rather than position doing the filtering.
_ENTITY_RE = re.compile(r"\b[A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*)*")

#: Which WAY a claim points. Two sentences about the peer gap that disagree on the
#: direction are two findings; two that agree are one, whatever units they use.
_DIRECTION: Tuple[Tuple[re.Pattern, str], ...] = (
    # "parity" is itself a direction word: a book already at parity has nothing to reach
    # for, so a sentence that mentions it is always saying the book is behind.
    (re.compile(r"\bbelow\b|\bbehind\b|\btrails?\b|\bshort of\b|\bparity\b", re.I),
     "below"),
    (re.compile(r"\babove\b|\bahead of\b|\bleads?\b|\bbeats?\b", re.I), "above"),
    (re.compile(r"\brose\b|\bgrew\b|\bimproved\b|\bup\b|\badded\b|\bgained\b", re.I), "up"),
    (re.compile(r"\bfell\b|\bslipped\b|\blost\b|\bdown\b|\bdeclined\b|\bshrank\b", re.I),
     "down"),
)


def topic_of_fact(fact_id: str) -> ClaimTopic:
    """The claim topic one fact id belongs to, or ``""`` for one in no family."""
    key = (fact_id or "").strip()
    matches = [(prefix, topic) for prefix, topic in _TOPIC_OF_PREFIX
               if key.startswith(prefix)]
    return max(matches, key=lambda m: len(m[0]))[1] if matches else ""


def topic_of(fact_ids: Sequence[str] = (), text: str = "") -> ClaimTopic:
    """The topic a bullet is ABOUT: its citations first, its words as the fallback.

    Citations first because they are exact — the writer says which facts the sentence
    rests on, and two sentences resting on ``peer.gap`` and ``peer.gap_value`` are making
    one claim however differently they read. A bullet citing several families is assigned
    the topic of its FIRST citation, which is the one it leads from.

    A bullet that cites nothing still has to be placed, so its words are read instead.
    That is weaker, and it is why the gate below only ever drops a repeat.
    """
    for fact_id in fact_ids or ():
        topic = topic_of_fact(fact_id)
        if topic:
            return topic
    for pattern, topic in _TOPIC_OF_TEXT:
        if pattern.search(text or ""):
            return topic
    return ""


def _direction(text: str) -> str:
    for pattern, way in _DIRECTION:
        if pattern.search(text or ""):
            return way
    return ""


def _entity(text: str) -> str:
    """The named driver a claim rests on — the product, country or industry it names.

    A run of capitalised words has its generic words trimmed off either end before it
    counts: "Writing Property at the same rate" reads as one capitalised run, and the
    driver in it is Property. Trimming rather than splitting keeps "Financial Lines"
    whole, which is a different book from "Financial Institutions".
    """
    for hit in _ENTITY_RE.findall(text or ""):
        words = [w for w in hit.split() if w]
        while words and words[0].lower() in _GENERIC_ENTITIES:
            words.pop(0)
        while words and words[-1].lower() in _GENERIC_ENTITIES:
            words.pop()
        if words:
            return " ".join(words).lower()
    return ""


#: Fact-id families whose ids name the driver they are about, and where in the id it sits.
#: ``mover.cyber`` is a two-part id; ``segment.industry.absent.renewable_energy`` is a
#: four-part one whose driver is the last part (see ``commentary_evidence._fact_id``).
#: Every other family — the peer gap, rank, share of wallet, the mix, the trend — is about
#: the whole book and names no driver.
_ENTITY_AT: Dict[str, int] = {"mover": 1, "pool": 1, "segment": -1}


def entity_of_fact(fact_id: str) -> str:
    """The driver a fact id is about — ``mover.cyber`` -> ``cyber`` — or ``""``."""
    parts = (fact_id or "").split(".")
    at = _ENTITY_AT.get(parts[0] if parts else "")
    return parts[at] if at is not None and len(parts) > abs(at) else ""


def claim_key(text: str) -> str:
    """What makes two SENTENCES the same claim: the finding, its driver, its direction.

    Deliberately blind to the figures. That is the whole difference from
    :func:`studio.template_fill.ledger.signature`, which keeps them: on the deterministic
    draft two figures mean two claims, but once the model may render one finding in points
    or in premium, keeping the figures is what lets the same point through three times.

    The driver is kept, so "Property is below the peer average" and "Cyber is below the
    peer average" stay two findings — and a country page saying of its own book what the
    overall page said of the whole book stays a finding of its own.

    Read from the words alone, for the callers that have only words: the whole-deck QA
    sweep sees finished prose long after the citations are gone.
    """
    topic = topic_of((), text)
    return f"{topic}|{_entity(text)}|{_direction(text)}" if topic else ""


def claim_of(fact_ids: Sequence[str] = (), text: str = "") -> str:
    """The same identity for a bullet that CITED its facts — read off the citations.

    Citations beat words, and not only because they are exact. A sentence's direction word
    is what tells "1.7pp below the peer average" apart from "1.7pp above" it, and it is
    also what fails to connect "the book is 1.7pp behind" with "closing that gap would add
    $39M" — same finding, and only one of them says which way it points. The ids do not
    have that problem: ``peer.gap`` and ``peer.gap_value`` ARE the distance, whichever way
    the sentence phrases it, so a cited claim is identified by its family and its driver
    and nothing else.

    An uncited bullet falls back to its words for the same two parts — and NOT to
    :func:`claim_key`, whose third part is the direction. The two keys have to be
    comparable or a page mixing cited and uncited bullets lets a repeat through on the
    seam: ``peer_gap|`` and ``peer_gap||below`` are the same finding and different
    strings. Dropping the direction inside the gate is safe in a way it is not for the
    deck-wide sweep, because two bullets on one page about one driver pointing opposite
    ways is a contradiction to fix, not two findings to keep.
    """
    cited = [f for f in (fact_ids or ()) if topic_of_fact(f)]
    if cited:
        return f"{topic_of_fact(cited[0])}|{entity_of_fact(cited[0])}"
    topic = topic_of((), text)
    return f"{topic}|{_entity(text)}" if topic else ""


# ── the plan ─────────────────────────────────────────────────────────────────


class PlannedColumn(Protocol):
    """What the plan needs of a commentary field — a section's ``Column`` satisfies it."""

    field_id: str
    node: str
    topic: str
    #: Where the column lands. Ownership is allocated per SLIDE, and the slide index is
    #: carried in the target's role (``note:<slide>:<shape>:<n>``) — see :func:`_page_of`.
    targets: Tuple[Any, ...]


@dataclass(frozen=True)
class FieldPlan:
    """One field's editorial job: what it is the home for, and what it may not say."""

    field_id: str
    node: str
    owns: Tuple[ClaimTopic, ...] = ()
    #: topic -> the node that is its home on THIS page.
    elsewhere: Tuple[Tuple[ClaimTopic, str], ...] = ()
    #: topic -> an earlier page in the deck that already made it.
    recaps: Tuple[Tuple[ClaimTopic, str], ...] = ()
    #: True for a field the allocation could not give a topic of its own. Its job is to
    #: SYNTHESISE what the page established rather than to own a finding — see
    #: :meth:`brief`. Previously such a field got no plan at all, which is why it repeated.
    synthesis: bool = False

    def brief(self) -> str:
        """The field's editorial ask, as a prompt block — empty when it has nothing to say."""
        parts: List[str] = []
        if self.owns:
            parts.append("THIS FIELD IS THE HOME FOR: "
                         + "; ".join(_TOPIC_LABEL.get(t, t) for t in self.owns)
                         + ". Lead on it.")
        if self.synthesis:
            # A page carries more fields than there are findings to go round, and the
            # leftovers are always the summary fields — Key Messages, Priorities. Handing
            # them nothing and no ban list (what this used to do) is what let them restate
            # the page. Their real job is the one no owning field can do: the forward view.
            parts.append(
                "THIS FIELD OWNS NO FINDING OF ITS OWN — it is the page's SYNTHESIS. Do not "
                "restate what the fields below established; take it forward. Say which "
                "products or industries the carrier must PROTECT, where premium or share "
                "moved against it, and where it trails the benchmark by enough to act on. "
                "Name the finding you are building on, then add the judgement or the "
                "decision it points to. A bullet that only repeats a finding is a wasted line.")
        if self.elsewhere:
            parts.append(
                "ANOTHER FIELD ON THIS PAGE IS THE HOME FOR THESE, so do not make any of "
                "them YOUR POINT — not in other words, not in another unit, not as a "
                "consequence. You MAY cite one in passing as the comparison that gives your "
                "own point its meaning (a movement needs the Marsh book it moved against), but the "
                "sentence must still be about your finding, not theirs: "
                + "; ".join(f"{_short(t)} ({node})" for t, node in self.elsewhere) + ".")
        if self.recaps:
            parts.append(
                "ALREADY MADE EARLIER IN THIS DECK: "
                + "; ".join(f"{_short(t)} (on {node})" for t, node in self.recaps)
                + ". A second appearance must ADD something — a driver, an implication or a "
                  "decision. Restating it is not adding.")
        return " ".join(parts)


@dataclass(frozen=True)
class EditorialPlan:
    """Every field's job, keyed by field id. Empty is a valid plan and changes nothing."""

    fields: Mapping[str, FieldPlan] = field(default_factory=dict)

    def brief(self, field_id: str) -> str:
        plan = self.fields.get(field_id)
        return plan.brief() if plan else ""

    def owner(self, topic: ClaimTopic, among: Iterable[str]) -> str:
        """Which of ``among`` is the home for ``topic``, or ``""`` when none of them is."""
        wanted = set(among)
        return next((fid for fid, plan in self.fields.items()
                     if fid in wanted and topic in plan.owns), "")

    def is_empty(self) -> bool:
        return not self.fields


EMPTY_PLAN = EditorialPlan()


# ── building it ──────────────────────────────────────────────────────────────


def _preferences(column: PlannedColumn) -> Tuple[ClaimTopic, ...]:
    """The topics this column would lead from, best first.

    Read off the column's own evidence focus, so the plan and the pack agree by
    construction: a column is offered ownership of exactly the families its brief already
    puts at the top of its evidence.
    """
    from studio.template_fill import commentary as C

    topics = [topic_of_fact(prefix) for prefix in C.evidence_focus(column.topic)]
    return tuple(dict.fromkeys(t for t in topics if t))


def _page_of(column: PlannedColumn) -> Tuple[Any, str]:
    """The slide a column lands on — ``(value set, slide index)``.

    Read off the first target's role, which is ``note:<slide>:<shape>:<n>``. A column with
    no target cannot be placed and falls into one bucket, where it is allocated against the
    other unplaceable ones rather than against a real page.
    """
    targets = tuple(getattr(column, "targets", ()) or ())
    if not targets:
        return (None, "")
    parts = str(targets[0].role).split(":")
    return (targets[0].value_set, parts[1] if len(parts) > 1 else "")


def _pages(columns: Sequence[PlannedColumn]) -> List[List[PlannedColumn]]:
    """``columns`` grouped by slide, in the order the deck reads them."""
    grouped: Dict[Tuple[Any, str], List[PlannedColumn]] = {}
    for column in columns:
        grouped.setdefault(_page_of(column), []).append(column)
    return list(grouped.values())


def _allocate(preferences: Mapping[str, Sequence[ClaimTopic]]) -> Dict[ClaimTopic, str]:
    """``{topic: field_id}`` — a draft pick over the section's columns.

    Round-robin rather than best-fit: every column takes its highest-ranked unclaimed
    topic before any column takes a second. A greedy pass would let the first column take
    the peer gap AND the standing AND the movement, which is the same page arguing with
    itself that this module exists to stop.

    Deterministic in the columns' own order, which is the order they appear on the page.
    """
    owner: Dict[ClaimTopic, str] = {}
    while True:
        picked = False
        for field_id, wanted in preferences.items():
            choice = next((t for t in wanted if t not in owner), "")
            if choice:
                owner[choice] = field_id
                picked = True
        if not picked:
            return owner


class EditorialPlanBuilder:
    """Builds the deck's plan one section at a time, in deck order.

    Sections are added in the order the deck reads, because "already made earlier" is a
    statement about order: the first page to own a topic is its home, and every later
    page that reaches for it is recapping.
    """

    def __init__(self) -> None:
        self._fields: Dict[str, FieldPlan] = {}
        #: topic -> the node that first owned it, anywhere in the deck.
        self._first_home: Dict[ClaimTopic, str] = {}

    def add_section(self, columns: Sequence[PlannedColumn]) -> "EditorialPlanBuilder":
        """One section's fields, allocated PAGE BY PAGE in the order the deck reads.

        A section is a BOOK and spans slides; ownership is a statement about one SLIDE.
        Allocating over the whole section meant the deck's headline page — "Positive Growth
        and Market Leadership Highlights", whose printed KPIs are premium and premium YoY —
        lost ``scale`` to a Key Messages box on the following slide, and was then forbidden
        to mention the numbers displayed beside it.

        Repetition ACROSS pages is a different rule with a different answer: ``recaps``,
        which is fed by :meth:`_remember` and still runs deck-wide, so a later page that
        reaches for what page two already said is told to add something or leave it.
        """
        for page in _pages(columns):
            self._add_page(page)
        return self

    def _add_page(self, columns: Sequence[PlannedColumn]) -> "EditorialPlanBuilder":
        """One slide's worth of fields: allocate its topics, then write each field's job."""
        if len(columns) < 2:
            # One field cannot repeat another, and a plan for it would only narrow what a
            # lone column may say. The recap memory is still fed, so a later page knows.
            self._remember(columns)
            return self
        preferences = {c.field_id: _preferences(c) for c in columns}
        owner = _allocate(preferences)
        nodes = {c.field_id: c.node for c in columns}
        for column in columns:
            owns = tuple(t for t, fid in owner.items() if fid == column.field_id)
            # A field with no home of its own used to get NO PLAN — no job and no ban
            # list — on the reasoning that banning every finding while offering none
            # leaves it nowhere to go. True, but the consequence was worse: the fields
            # left over by the allocation are the summary ones (Key Messages, Carrier
            # Priorities), and an unplanned summary field simply restated the page. It
            # now gets a plan whose job is synthesis, which is the thing no owning field
            # is free to do.
            self._fields[column.field_id] = FieldPlan(
                field_id=column.field_id, node=column.node, owns=owns,
                synthesis=not owns,
                elsewhere=tuple((t, nodes[fid]) for t, fid in sorted(owner.items())
                                if fid != column.field_id),
                recaps=tuple((t, self._first_home[t]) for t in owns
                             if t in self._first_home),
            )
        self._remember(columns, owner)
        return self

    def _remember(self, columns: Sequence[PlannedColumn],
                  owner: Optional[Mapping[ClaimTopic, str]] = None) -> None:
        """Record where each topic FIRST found a home, for the pages that follow."""
        nodes = {c.field_id: c.node for c in columns}
        for topic, field_id in (owner or {}).items():
            self._first_home.setdefault(topic, nodes.get(field_id, ""))
        for column in columns:
            for topic in _preferences(column):
                self._first_home.setdefault(topic, column.node)

    def build(self) -> EditorialPlan:
        return EditorialPlan(fields=dict(self._fields))


def plan_deck(sections: Sequence[Sequence[PlannedColumn]]) -> EditorialPlan:
    """The whole deck's editorial plan, sections in deck order."""
    builder = EditorialPlanBuilder()
    for columns in sections:
        builder.add_section(columns)
    return builder.build()


# ── the gate ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Repeat:
    """One bullet dropped for making a claim the page had already made."""

    field_id: str
    text: str
    topic: ClaimTopic
    home: str                    # the field id that kept the claim

    @property
    def reason(self) -> str:
        return (f"it makes the point '{_short(self.topic)}', which field {self.home} "
                f"already makes on this page — write this field on something else")


@dataclass(frozen=True)
class _Bullet:
    field_id: str
    text: str
    fact_ids: Tuple[str, ...] = ()
    #: observation | interpretation | recommendation, as the writer declared it.
    kind: str = "observation"


def _claim_for(bullet: "_Bullet", plan: EditorialPlan) -> str:
    """The identity a bullet is deduped on, given the page's plan.

    A SYNTHESIS field's bullets are namespaced to that field, but ONLY when they carry an
    interpretation or a recommendation. Its job is to build on a finding another field owns
    and take it forward, and :func:`claim_of` reads identity off the FIRST citation — so the
    supporting fact it names matches the owning field's copy and the gate would drop it
    every time. That is the gate deleting the one field whose purpose is to reference.

    The kind is what keeps the exemption honest, and it has to be here rather than left to
    the judge. A synthesis bullet that is a bare OBSERVATION is a restatement however it is
    worded, so it keeps the shared identity and loses to the owning field exactly as before
    — otherwise "one finding, one page" stops holding the moment a page has a summary
    field. One that interprets or recommends has added the thing the shared claim does not
    capture, and is judged on whether it really did by the verifier, which reads the text.
    """
    claim = claim_of(bullet.fact_ids, bullet.text)
    if not claim:
        return claim
    field_plan = plan.fields.get(bullet.field_id)
    adds = (bullet.kind or "observation").strip().lower() in ("interpretation", "recommendation")
    if field_plan is not None and field_plan.synthesis and adds:
        return f"{claim}@{bullet.field_id}"
    return claim


def dedupe(bullets: Sequence[Tuple[str, str, Sequence[str]]], *,
           plan: EditorialPlan = EMPTY_PLAN,
           ) -> Tuple[Dict[str, List[str]], List[Repeat]]:
    """One claim per topic per page: ``({field_id: [text]}, [dropped])``.

    ``bullets`` are ``(field_id, text, fact_ids)`` — or ``(field_id, text, fact_ids, kind)``
    — in the page's own order.

    Which copy survives is the plan's call — the field the topic was allocated to keeps
    it, so the page's argument lands where it was planned to. With no plan, or when the
    home wrote nothing on it, the first copy in page order wins.

    **The rule has no exception for a field it empties**, and that is deliberate. The
    tempting guard — always keep a field's last line — puts the repetition straight back
    on the page in the one case this module exists for: three fields that all wrote only
    the peer gap keep one line each, and the slide says it three times again. So a field
    left with nothing here becomes a :class:`~commentary_batch.Failure` like any other,
    carrying the reason, and the machinery that already answers "the page must still say
    something" answers it: the repair round writes the field again on a point the page has
    not made, and failing that the deterministic draft stands — and the draft has been
    through the :class:`~studio.template_fill.ledger.ClaimLedger`, so it is not a repeat
    either.
    """
    # ``(field_id, text, fact_ids)`` or ``(field_id, text, fact_ids, kind)``. The kind is
    # optional so a caller that does not track it — the deck-wide sweep, a test — keeps
    # working and gets the strict reading (``observation``), which is the old behaviour.
    items = [_Bullet(b[0], b[1], tuple(b[2] or ()),
                     (b[3] if len(b) > 3 and b[3] else "observation"))
             for b in bullets]
    # The CLAIM, not the topic. A growth column naming three industries Marsh places and
    # this carrier does not is three findings that share one fact family, and deduping on
    # the family would cut it to one line — the thinning this module is written to avoid.
    claims = [_claim_for(b, plan) for b in items]
    winners = _winners(items, claims, plan)

    kept: Dict[str, List[str]] = {b.field_id: [] for b in items}
    dropped: List[Repeat] = []
    survivors: Set[int] = set(winners.values())
    for index, (bullet, claim) in enumerate(zip(items, claims)):
        if not claim or index in survivors:
            kept[bullet.field_id].append(bullet.text)
            continue
        dropped.append(Repeat(bullet.field_id, bullet.text, claim.split("|")[0],
                              items[winners[claim]].field_id))
    if dropped:
        logger.info("editorial: dropped %d repeated claim(s): %s", len(dropped),
                    ", ".join(f"{r.field_id}~{r.topic}" for r in dropped))
    return kept, dropped


def _winners(items: Sequence[_Bullet], claims: Sequence[str],
             plan: EditorialPlan) -> Dict[str, int]:
    """``{claim: the index of the bullet that keeps it}`` — the home's copy, else the first.

    Ownership is allocated by TOPIC and repetition is judged by CLAIM, so the home for a
    claim is the home for the family it belongs to: the field that owns headroom keeps the
    Cyber whitespace line and the Marine one both, and another field loses either.
    """
    fields = {b.field_id for b in items}
    winners: Dict[str, int] = {}
    for claim in dict.fromkeys(c for c in claims if c):
        candidates = [i for i, c in enumerate(claims) if c == claim]
        home = plan.owner(claim.split("|")[0], fields)
        winners[claim] = next((i for i in candidates if items[i].field_id == home),
                              candidates[0])
    return winners
