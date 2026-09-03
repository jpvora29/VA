"""Per-page commentary — fill a template's qualitative prose slots from the facts.

Section-aware (see :mod:`studio.template_fill.sections`): on slides that carry
fact-derivable commentary (Trading Summary, SWOT, Highlights, Summary) the ellipsis
prose boxes are bound to ``note:<slot-key>`` roles and filled with whole sentences that
are 100% faithful by construction — each column is composed by the SAME fact-grounded
composers as the per-country feedback panels (:mod:`studio.template_fill.feedback`), so
the deck argues in one voice; SWOT quadrants, and any column those composers cannot
carry, fall back to the rule-based :mod:`studio.narrate.commentary`.

When an LLM is configured it WRITES the column rather than re-wording it: given the draft
and the column's own brief (:data:`_TOPIC_BRIEF`) it may fold two claims into one sentence
or drop a line that adds nothing, within the bounds :func:`min_lines` sets. What comes back
is checked — for faithfulness (every number must already appear in the deterministic
draft), for READING (whole sentences, none of the phrases that make prose sound generated),
and for SHAPE (one carrier-name opening per column, no bullet opening on a bare measure).
A rewrite that fails any of those is dropped and the draft stands — and the draft has had
its own repeated openings varied (:mod:`studio.template_fill.openings`), so the fallback is
no longer the roll-call it used to be.

Qualitative-only sections (relationship Feedback) are deliberately left as placeholders —
premium data can't honestly fill them.

Mirrors :mod:`studio.template_fill.grids`: ``augment`` re-binds slots, ``values``
produces the keyed text — both fold into the same doc the preview and fill consume.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from logger import get_logger
from studio.template_fill import openings
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Slide, Template
from studio.template_fill.sections import Section, section_of

logger = get_logger(__name__)

_ELLIPSIS = re.compile(r"…|\.{3,}")
# Sections whose prose we can ground in premium facts.
_COMMENTARY_SECTIONS = {
    Section.TRADING_SUMMARY, Section.SWOT, Section.HIGHLIGHTS, Section.SUMMARY,
}
# The commentary voice chosen in Setup → the instruction appended to the writing prompt.
# Every style keeps the same faithfulness guardrails; only the length shifts. Each style
# still demands whole sentences: a QBR page is read aloud to an executive team, and a
# telegraphic fragment ("Momentum: Cyber +97%") is not something a partner would say.
_STYLE_DIRECTIVE: Dict[str, str] = {
    "concise": "Write each line as ONE complete sentence carrying the figure and its "
               "consequence.",
    "balanced": "Write each line as TWO complete sentences: what the figures show, then what "
                "it means for this account.",
    "detailed": "Write each line as TWO OR THREE complete sentences: what the figures show, "
                "what moved them, and what the account should do about it.",
}

# Commentary is written as BULLET POINTS, one per line — the deck renders each line as its
# own bulleted paragraph, so the line structure is part of the contract.
#
# The model is allowed to MERGE or DROP one bullet, and that permission is the point. The
# draft composes each claim to stand alone, so a column often carries two thin facts that a
# writer would fold into one sentence, or a closing line that adds nothing once the others
# are written. Forbidding every structural move — the old rule was "return exactly the same
# number of lines" — left the model with nothing to do but swap adjectives, and any rewrite
# that dropped an unverifiable figure came back a line short and was thrown away wholesale.
def _bullet_rules(wanted: int) -> str:
    """The line-structure contract for a column of ``wanted`` draft bullets."""
    floor = min_lines(wanted)
    room = ("You may merge two bullets that make one point, or drop a bullet that adds "
            f"nothing once the others are written: return between {floor} and {wanted} "
            "lines. " if floor < wanted else f"Return {wanted} line. ")
    return (
        "The draft is a bullet list, ONE BULLET PER LINE, in priority order. " + room +
        "Keep the order. Do not write any bullet character, dash or number at the start of "
        "a line — the slide adds the bullet itself. "
    )


def min_lines(wanted: int) -> int:
    """The fewest bullets a rewrite of ``wanted`` may come back with.

    One merge or one drop, never two, and never below two lines on a column that had them:
    a rewrite that halves a page is not an edit, it is a different page.
    """
    return max(min(wanted, 2), wanted - 1)


# What each column is FOR. The old prompt was identical for every topic, which is most of
# why Key Messages and Challenges read the same: they draw on the same six figures, so
# without a brief telling them apart the model has no reason to write them apart.
#
# Each brief says what question the column answers, the trap it falls into, and the move
# that gets it out. Kept to what is true of the column regardless of carrier — anything
# carrier-specific belongs in the facts, not the prompt.
_TOPIC_BRIEF: Dict[str, str] = {
    "thesis":
        "THIS COLUMN: the one claim the rest of the deck exists to argue. State where this "
        "account STANDS — a position a leadership team can agree with or push back on — and "
        "name the tension inside it. Not a summary of the figures below it. ",
    "key_messages":
        "THIS COLUMN: what the account team must be able to say from memory in the room. "
        "Each line is a POSITION, not a statistic — the figure is the evidence for the "
        "claim, never the claim itself. Do not open a line with the carrier's name and a "
        "number; lead with what is true and let the figure follow. ",
    "challenges":
        "THIS COLUMN: what threatens this book over the next twelve months. Name the "
        "MECHANISM, not the metric — which line, at which renewal, losing to what. A "
        "restated decline is not a challenge; the reason it will continue is. ",
    # ``working`` and ``growth`` are composer kinds rather than template column headers:
    # they fill the per-country feedback panels (studio.template_fill.feedback), which ask
    # the same questions of a narrower book.
    "working":
        "THIS COLUMN: what is working, and whether it was won or merely carried by the "
        "market. Growth that only matched the Marsh pool is not a success — say which of "
        "the two this was, and what it cost to get. ",
    "growth":
        "THIS COLUMN: the headroom worth going after, and what taking it is worth in "
        "premium. Whitespace is business somebody else already writes; say that plainly "
        "rather than calling it addressable, and name where it sits. ",
    "reflections":
        "THIS COLUMN: an honest read on the year just closed — what the account got right, "
        "what it misjudged, and what that says about how the next one should be run. Write "
        "it as a partner who was in the room, not as a scorecard. ",
    "performance":
        "THIS COLUMN: how the book actually performed and WHY it moved. Every line should "
        "carry a driver — a line of business, a renewal, a shift in the Marsh pool — so the "
        "reader learns something the chart beside it does not already show. ",
    "priorities":
        "THIS COLUMN: what happens next. Each line names an ACTION, who has to move, and "
        "the premium at stake. End on the ask — the one thing this carrier must do for the "
        "next quarter to look different. Never close on advice true of any carrier. ",
    "strengths":
        "THIS COLUMN: what this carrier can defend, and against whom. A strength nobody "
        "could take away is not worth a line. ",
    "weaknesses":
        "THIS COLUMN: where the book is exposed. Be specific about the exposure, not "
        "apologetic about the number. ",
    "opportunities":
        "THIS COLUMN: headroom this carrier could realistically take, and what taking it "
        "would be worth. Whitespace is premium someone else already writes — say that "
        "plainly rather than calling it addressable. ",
    "threats":
        "THIS COLUMN: what could go wrong that is not already going wrong. Name the source. ",
}

# The questions each column must ANSWER. Never rendered — they never reach a slide — but
# they are what turns a brief into a specification. ``_TOPIC_BRIEF`` says what a column is
# FOR; a model given only that still chooses which of the facts in front of it to use, and
# reaches for the headline every time because the headline is the easiest thing to write
# about. Naming the questions makes the industry evidence the expected answer rather than
# optional colour.
#
# They are also the contract the deterministic composers order their claims by, so the
# draft the model is shown already answers them in the same sequence.
_TOPIC_QUESTIONS: Dict[str, Tuple[str, ...]] = {
    "working": (
        "What grew, and was it won on share or carried by the pool?",
        "Which industry or client segment does this book place BEST in, and how far above "
        "the average it achieves where it writes?",
        "What did the growth actually buy — rank, share, or neither?",
    ),
    "challenges": (
        "Where did the book lose share, and was the pool behind it growing or shrinking?",
        "Which named industry or client segment is the ground being given in, and what is "
        "that worth?",
        "How much of the book rests on its largest few segments, and which of those is "
        "moving the wrong way?",
        "Where did Marsh demand grow hardest and this book take least of it?",
    ),
    "growth": (
        "Which industries does Marsh place materially in that this book writes NOTHING of, "
        "and how much premium is that?",
        "Which does it write BELOW the average it achieves where it writes, and what would "
        "parity be worth?",
        "Which does it write below the top-5 peer average, and what is that worth?",
        "Which industry proves the line CAN be placed better, and at what share?",
    ),
    "key_messages": (
        "What must happen next, in which named industry, product or client segment?",
        "What premium is at stake, and measured against which benchmark?",
        "What is worth defending, and what says it is at risk?",
    ),
    "priorities": (
        "Which named industry, product or segment carries the most premium at stake?",
        "What has to move there, and what is it worth?",
        "What is still unconfirmed before the ask becomes a commitment?",
    ),
    "thesis": (
        "Where does this account STAND, in one claim a leadership team can push back on?",
        "What is the tension inside that position?",
    ),
    "performance": (
        "What moved, and which industry, segment or line drove it?",
        "Did the pool move with it or against it?",
    ),
    "reflections": (
        "What did the account get right, and what did it misjudge?",
        "Which named segment does that judgement rest on?",
    ),
}


def _questions_rule(topic: str) -> str:
    """The column's hidden question set as a prompt block. Never rendered on a slide."""
    questions = _TOPIC_QUESTIONS.get(topic, ())
    if not questions:
        return ""
    listed = " ".join(f"({i}) {q}" for i, q in enumerate(questions, 1))
    return ("ANSWER THESE QUESTIONS in this order, and only where the evidence supports an "
            f"answer — never print a question, and never number your lines: {listed} ")


# Which columns diagnose and which may instruct. The deck used to close every page on
# "the call is to defend Cyber, scale Financial Lines, fix Casualty" — six products, no
# figures, and true of any carrier with six lines. Diagnosis is what the feedback columns
# are for; the instruction belongs where a team is expected to act on it, and only when it
# says where and how much.
_IMPERATIVE_TOPICS = frozenset({"key_messages", "priorities"})

_DIAGNOSTIC_RULE = (
    "VOICE FOR THIS COLUMN: diagnose, do not instruct. State the position, the mechanism "
    "behind it and what is at stake, and let the reader draw the conclusion. Do not tell "
    "the carrier what to do and do not open a line with an instruction. "
)

_IMPERATIVE_RULE = (
    "VOICE FOR THIS COLUMN: you may say what must happen — but ONLY tied to a named "
    "industry, product or client segment AND a premium figure from the evidence. Never "
    "write an instruction against a bare product name: 'defend Cyber', 'scale Financial "
    "Lines', 'fix Casualty', 'selectively pursue Property' are all refused. An instruction "
    "with no named segment and no figure behind it is a slogan, not a message. "
)


def _voice_rule(topic: str) -> str:
    return _IMPERATIVE_RULE if topic in _IMPERATIVE_TOPICS else _DIAGNOSTIC_RULE


# Who is writing. Insurer Consulting Group partners write for carrier boards: plain,
# declarative, unhedged, and always answerable to the figure on the page.
_VOICE = (
    "You are a partner in Marsh's Insurer Consulting Group with twenty years advising "
    "carriers, writing the commentary a carrier's executive team will read in their "
    "quarterly business review. Write the way you would speak to that room: plainly, in the "
    "past tense, in complete sentences, with a view the figures support and no hedging. "
    "Distinguish market movement from share movement, and use the market's own words — GWP, "
    "share of wallet, rank, renewal book, capture rate, headroom, placement. "
)

# What separates a consultant's page from a generated one. These are the habits that make
# commentary read as machine-written, and they are named explicitly because a model asked
# only for "professional" prose reaches for every one of them.
_CRAFT = (
    "CRAFT: every line must be a complete sentence with a subject and a verb and end in a "
    "full stop — never a heading, a label, a fragment, or a 'Topic: value' pair. Say what "
    "happened and what it means; do not restate a figure you have already given, do not "
    "explain what a percentage is, and do not close on advice that would be true for any "
    "carrier. Never write the words 'indicating', 'showcasing', 'underscoring', "
    "'demonstrating', 'reflecting a', 'positioning the carrier', 'solid foothold', 'robust', "
    "'strategic', 'leverage', 'key driver', 'landscape', 'moving forward', 'it is worth "
    "noting', 'overall,', 'untapped', 'low-hanging', 'ripe for', 'significant "
    "opportunity', 'huge potential', 'a natural fit', or 'penetrate the market'. "
)

_FAITHFULNESS = (
    "HARD RULES: keep EVERY number, currency amount, percentage and rank EXACTLY as written — "
    "never invent, recalculate or round a figure; never name a competitor carrier. "
)


def _style_system(style: Optional[str], *, topic: str = "", wanted: int = 1,
                  subject: str = "") -> str:
    """The system prompt for one column: voice, craft, faithfulness, shape, and its brief."""
    return (_VOICE + _CRAFT + _FAITHFULNESS + _openings_rule(subject)
            + _bullet_rules(wanted) + _TOPIC_BRIEF.get(topic, "")
            + _voice_rule(topic) + _questions_rule(topic)
            + _STYLE_DIRECTIVE.get((style or "balanced").lower(),
                                   _STYLE_DIRECTIVE["balanced"]))


def _openings_rule(subject: str) -> str:
    """The instruction behind the opening gate, so the model is told the rule it is held to."""
    if not subject:
        return ""
    return (f"OPENINGS: name {subject} ONCE in this column and then write about 'the book'. "
            f"At most one line may begin with '{subject}'. Never leave a line that is a bare "
            f"measure and a value ('Rank improved to 4th.', 'Share of wallet rose 0.6pp.') — "
            f"a line that opens on a measure must go on to say why it moved or what follows "
            f"from it. ")


def _cx(sh: Shape) -> float:
    return sh.x + sh.w / 2.0


# A prose box the author left filled with EXAMPLE commentary rather than ellipses reads as
# a sentence — several words of running text. Headers, captions and KPI tokens never do.
_MIN_PROSE_WORDS = 8


def _reads_as_prose(text: str) -> bool:
    return len((text or "").split()) >= _MIN_PROSE_WORDS


def _is_prose_slot(sh: Shape) -> bool:
    """True for a commentary box: an ellipsis "fill me", or authored example prose.

    Templates mark a prose slot either way — ``…………`` in the earlier decks, a paragraph of
    sample commentary in the current ones. Both must be recognised, or a deck ships the
    author's example narrative as if it were this carrier's story.
    """
    if sh.kind != "text" or not sh.paragraphs:
        return False
    first = sh.paragraphs[0] or ""
    return bool(_ELLIPSIS.search(first)) or _reads_as_prose(first)


def _column_topic(slide: Slide, shape: Shape) -> str:
    """The topic keyword for a prose box = its nearest header above (same column)."""
    headers = [s for s in slide.shapes
               if s.kind == "text" and s is not shape and s.text.strip()
               and not _is_prose_slot(s) and s.y < shape.y and len(s.text.strip()) <= 32]
    if not headers:
        return slide.title()
    return min(headers, key=lambda s: abs(_cx(s) - _cx(shape))).text.strip()


# A prose box whose column header names no known topic falls back to its SECTION's topic:
# a highlights/summary page wants the headline, a four-column page its key messages.
_SECTION_DEFAULT_TOPIC: Dict[Section, str] = {
    Section.HIGHLIGHTS: "thesis",
    Section.SUMMARY: "thesis",
}

_HEADER_TOPICS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("reflection",), "reflections"),
    (("performance", "ytd"), "performance"),
    (("priorit",), "priorities"),
    (("message",), "key_messages"),
    (("strength",), "strengths"),
    (("weak",), "weaknesses"),
    (("opportun",), "opportunities"),
    (("threat",), "threats"),
)


def _topic_key(header: str, section: Section = Section.OTHER) -> str:
    low = header.lower()
    for keywords, topic in _HEADER_TOPICS:
        if any(k in low for k in keywords):
            return topic
    return _SECTION_DEFAULT_TOPIC.get(section, "key_messages")


def _prose_targets(template: Template) -> List[Dict[str, Any]]:
    """``[{slide_idx, shape_id, topic}]`` for every fillable prose box in a commentary section.

    One target per BOX, not per paragraph: the whole box is one bullet list, and the fill
    engine's commentary writer lays the bullets out over the box's paragraphs (appending and
    blanking as needed), so neither a stale ``………`` line nor a leftover line of the author's
    example prose survives.
    """
    out: List[Dict[str, Any]] = []
    for slide in template.slides:
        section = section_of(slide)
        if section not in _COMMENTARY_SECTIONS:
            continue
        for sh in slide.shapes:
            if _is_prose_slot(sh):
                out.append({"slide_idx": slide.index, "shape_id": sh.shape_id,
                            "topic": _topic_key(_column_topic(slide, sh), section)})
    return out


def _role(slide_idx: int, shape_id: int, para: int = 0) -> str:
    return f"note:{slide_idx}:{shape_id}:{para}"


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Re-bind (or add) each commentary prose box as a ``note:<slide>:<shape>:0`` role.

    A box the slot detector never saw — authored prose carries no ``x`` placeholder — is
    ADDED here, so it fills rather than shipping the author's example narrative.
    """
    from studio.template_fill.slots import Slot

    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []
    stale: List[R.Binding] = []
    for t in _prose_targets(template):
        shape = template.shape(t["slide_idx"], t["shape_id"])
        role = _role(t["slide_idx"], t["shape_id"])
        where = ["para", 0]
        b = by_key.get(Slot(t["slide_idx"], t["shape_id"], where, "", "text", "").key)
        if b is not None:
            b.role, b.placeholder = role, False
        else:
            token = shape.paragraphs[0] if (shape and shape.paragraphs) else ""
            extra.append(R.Binding(
                slot=Slot(t["slide_idx"], t["shape_id"], where, token, "text", ""),
                role=role, placeholder=False))
        # The box's LATER paragraphs are the writer's to lay out; any binding on them (from a
        # token scan, or an earlier augment pass) would fight it, so they are released.
        stale += [x for x in bindings
                  if x.slot.slide_idx == t["slide_idx"] and x.slot.shape_id == t["shape_id"]
                  and list(x.slot.where)[:1] == ["para"] and int(x.slot.where[1]) > 0]
    for b in stale:
        b.role, b.placeholder = None, True
    if extra:
        logger.info("commentary: added %d prose box(es) the token scan could not see", len(extra))
    return bindings + extra


# ── text generation ──────────────────────────────────────────────────────────


# A bullet character the model may prefix a line with despite being told not to.
_LEADING_BULLET = re.compile(r"^\s*(?:[-•▪◦*·]|\d+[.)])\s+")

# The tells of machine-written prose. The prompt forbids them; this is what makes the ban
# stick — a rewrite carrying one of these is dropped and the deterministic draft stands,
# which is the better page anyway. Kept to phrases no partner would write on a QBR slide,
# so a legitimate rewrite is never thrown away.
_AI_TELLS = re.compile(
    r"\b(?:indicat(?:es|ing)|showcas\w+|underscor\w+|demonstrat(?:es|ing)|reflecting a|"
    r"solid foothold|robust|strategic(?:ally)?|leverag\w+|key driver|landscape|"
    r"moving forward|it is worth noting|testament to|poised to|ever-\w+|"
    r"significant potential|delve)\b",
    re.I,
)


def _is_whole_sentence(line: str) -> bool:
    """A finished sentence, not a label or a fragment: it ends in a full stop."""
    return line.rstrip().endswith((".", "?", "!"))


# How many bullets in one column may open on the carrier's name. One: a column says who it
# is about, then talks about the book.
_MAX_SUBJECT_OPENINGS = 1


def _accept(lines: List[str], *, wanted: int, node: str, subject: str = "") -> Optional[str]:
    """The rewritten bullets, or ``None`` when the rewrite is worse than the draft.

    A rewrite is refused when it changed the column's SHAPE beyond one merge or drop
    (:func:`min_lines`), left a line as a fragment, reached for one of the phrases that make
    commentary read as generated, named the carrier at the head of more than one line, or
    left a bullet that is a measure and a value and nothing else
    (:func:`studio.template_fill.commentary_metrics.is_restatement`).

    The last two are what make a page read as written rather than produced, and they are
    enforced here rather than hoped for in the prompt for the same reason the AI tells are:
    a model asked for a partner's voice will still reach for the roll-call unless the
    roll-call is refused.
    """
    from studio.template_fill import commentary_metrics

    floor = min_lines(wanted)
    if not floor <= len(lines) <= wanted:
        logger.info("commentary: %s rewrite returned %d line(s) for %d bullet(s) (allowed "
                    "%d-%d) — keeping the deterministic draft",
                    node, len(lines), wanted, floor, wanted)
        return None
    fragment = next((ln for ln in lines if not _is_whole_sentence(ln)), None)
    if fragment is not None:
        logger.info("commentary: %s rewrite left a fragment (%.40r) — keeping the "
                    "deterministic draft", node, fragment)
        return None
    tell = _AI_TELLS.search("\n".join(lines))
    if tell is not None:
        logger.info("commentary: %s rewrite reads as generated (%r) — keeping the "
                    "deterministic draft", node, tell.group(0))
        return None
    named = openings.subject_openings(lines, subject) if subject else 0
    if named > _MAX_SUBJECT_OPENINGS:
        logger.info("commentary: %s rewrite opens %d line(s) on %r — keeping the "
                    "deterministic draft", node, named, subject)
        return None
    readout = next((ln for ln in lines if commentary_metrics.is_restatement(ln)), None)
    if readout is not None:
        logger.info("commentary: %s rewrite left a metric read-out (%.40r) — keeping the "
                    "deterministic draft", node, readout)
        return None
    return "\n".join(lines)


# Commentary is the deliverable, not an inner loop. The `fast` tier is the one
# ``core.initialization`` describes as "the mechanical inner-loop nodes" — minimal reasoning
# effort — and asking it for a partner's judgement got a partner's vocabulary over a
# clerk's argument. `balanced` is the cheapest tier that can actually make the editorial
# calls the rules above now allow (merge these two claims, cut that one, lead with the
# consequence).
_COMMENTARY_TIER = "balanced"


def _rewrite(text: str, *, node: str, style: Optional[str] = None, topic: str = "",
             subject: str = "", facts: Optional[Dict[str, Any]] = None) -> str:
    """The column as a model writes it from EVIDENCE, or the deterministic draft.

    ``text`` is the rule composers' newline-separated bullet list. It is passed on as the
    draft — the claims the composers selected and the order they put them in — but the
    model is given the facts themselves (:mod:`studio.template_fill.commentary_evidence`)
    and the ICG definitions of the terms in play (:mod:`core.definitions`), so what comes
    back is written from the book rather than reworded from a sentence.

    Everything the model returns has to survive both verifiers (numbers against cited
    facts, then claims and term use against the evidence and the glossary) and then
    :func:`_accept`, which rules on shape and reading. If any of that refuses it, the
    deterministic draft stands.
    """
    if not text:
        return text
    from studio.ai import client
    from studio.template_fill import commentary_evidence as E
    from studio.template_fill import commentary_writer as W

    draft = tuple(ln for ln in text.splitlines() if ln.strip())
    wanted = len(draft)

    def call() -> Optional[str]:
        pack = E.build_pack(facts or {})
        if not pack.items:                  # nothing to cite — the draft is all we have
            return None
        write = W.make_writer()
        lines = list(write(W.ColumnRequest(
            topic=topic, pack=pack, draft=draft, subject=subject, style=style or "balanced",
            bullets=wanted, brief=_TOPIC_BRIEF.get(topic, ""),
            voice=_style_system(style, topic=topic, wanted=wanted, subject=subject),
        )))
        return _accept([_LEADING_BULLET.sub("", ln).strip() for ln in lines],
                       wanted=wanted, node=node, subject=subject)

    return client.run_or_fallback(call, lambda: text)


# What each prose column asks of the facts, as ``(composer, how many of its sentences)``.
#
# The summary page's columns ask the same questions of the same book as the per-country
# feedback panels do — what worked, what did not, where the headroom is, what the account
# team should be able to say — so they are answered by the SAME composers
# (:func:`studio.template_fill.feedback.points`). One voice across the deck, and every
# sentence already carries the figure behind it.
_TOPIC_PANELS: Dict[str, Tuple[Tuple[str, int], ...]] = {
    # The summary page states the thesis and then the movement behind it; every other page
    # reports a part of the book. One page in a deck should say where the account stands.
    "thesis": (("thesis", 1), ("working", 1)),
    "reflections": (("working", 1), ("challenges", 1), ("growth", 1)),
    "performance": (("working", 2), ("challenges", 2)),
    "priorities": (("growth", 3),),
    "key_messages": (("key_messages", 3),),
}


def panel_facts(result) -> Dict[str, Any]:
    """The fact set the prose columns are composed from — ``{}`` when it can't be loaded.

    An empty set is not an error: a thin book or a dataset with no peer benchmark simply
    sends the columns back to the rule-based narrator.
    """
    from studio.template_fill import feedback

    try:
        return feedback.facts_for(result)
    except Exception as exc:  # noqa: BLE001 — commentary must never break the doc
        logger.warning("commentary: panel facts unavailable (%s) — using the rule narrator", exc)
        return {}


def _panel_points(topic: str, facts: Dict[str, Any]) -> List[str]:
    """The composed sentences for ``topic``, de-duplicated, or ``[]`` if it has no panel."""
    from studio.template_fill import feedback

    panels = _TOPIC_PANELS.get(topic)
    if not panels or not facts:
        return []
    out: List[str] = []
    for kind, take in panels:
        for point in feedback.points(kind, facts)[:take]:
            if point not in out:
                out.append(point)
    return out


def _topic_points(result, topic: str, facts: Optional[Dict[str, Any]] = None) -> List[str]:
    """Complete, fact-grounded commentary sentences for a column/quadrant topic.

    One sentence per bullet — the deck renders each as its own bulleted paragraph, so they
    are kept as separate strings all the way through rather than joined into a paragraph.

    The panel composers answer the four prose columns; the SWOT quadrants, and any column
    the panels cannot carry, fall back to the rule-based narrator.
    """
    return (_panel_points(topic, facts if facts is not None else panel_facts(result))
            or _narrated_points(result, topic))


def _narrated_points(result, topic: str) -> List[str]:
    """The rule-based narrator's points for ``topic`` — the fallback, and the SWOT source."""
    from studio.narrate.commentary import build_commentary, build_initiatives, build_swot

    headline, points, actions = build_commentary(result)

    def by_label(*labels: str) -> List[str]:
        return [p["text"] for p in points if p["label"].rstrip(".") in labels]

    if topic == "reflections":
        return [headline] + by_label("Momentum", "Soft spots")[:2]
    if topic == "performance":
        return by_label("Momentum", "Soft spots", "Penetration")[:3] or [headline]
    if topic == "priorities":
        cards = build_initiatives(result)
        if cards:
            return [f"{c['title']} — {c['body']}" for c in cards[:3]]
        return actions[:3]
    if topic == "key_messages":
        return actions[:3] or [p["text"] for p in points[:2]] or [headline]
    if topic in ("strengths", "weaknesses", "opportunities", "threats"):
        swot = build_swot(result)
        return list(getattr(swot, topic, []) or [])[:3]
    return [headline]


def bullet_list(points: List[str]) -> str:
    """Fold commentary points into the one-bullet-per-LINE form the fill engine renders."""
    return "\n".join(p.strip() for p in points if p and p.strip())


def with_ledger(ledger, narratives: Optional[List[Any]] = None):
    """This provider bound to a deck's claim ledger and narrative collector.

    The provider list is uniform ``(template, result)`` callables, so the per-deck ledger
    (:class:`~studio.template_fill.ledger.ClaimLedger`) and the list each page's
    :class:`~studio.narrative.SlideNarrative` is appended to are injected here rather than
    threaded through every provider's signature.
    """
    def provider(template: Template, result) -> Dict[str, Any]:
        return values(template, result, ledger=ledger, narratives=narratives)

    provider.__module__ = __name__
    return provider


def _page_narratives(targets: List[Dict[str, Any]], result, facts: Dict[str, Any]) -> List[Any]:
    """One :class:`~studio.narrative.SlideNarrative` per prose-bearing PAGE.

    Built from the FACTS rather than parsed back out of the rendered prose: the contract
    describes the argument a page is making, and re-reading sentences to recover it would
    be both lossy and one more thing to keep in step with the composers.

    A page's job comes from its FIRST column's topic — the leftmost column is the one the
    page leads on — which is what makes two pages doing the same job visible to QA.
    """
    from studio.template_fill.stance import narrative_for

    if not facts:
        return []
    primary: Dict[int, str] = {}
    for t in targets:                       # targets arrive in slide/reading order
        primary.setdefault(t["slide_idx"], t["topic"])
    name = str(getattr(result, "subject", "") or "")
    out = []
    for topic in primary.values():
        narrative = narrative_for(facts, topic, name=name,
                                  said=_topic_points(result, topic, facts))
        if narrative is not None:
            out.append(narrative)
    return out


# The topic whose column is about what to DO — where a portfolio stance belongs.
_STANCE_TOPIC = "priorities"

# What a prose column can hold before it stops being read. The extras below deliberately
# offer MORE candidates than this — the ledger picks the first that are still unsaid, so a
# column whose leading claims were spoken for on an earlier page still fills up here.
_MAX_COLUMN_BULLETS = 4


def _with_portfolio_stance(said: List[str], topic: str, result, extras=None) -> List[str]:
    """A column opened on the portfolio's stance and DEEPENED with its own extra claims.

    Two jobs, because they are two halves of one idea. The priorities column opens on the
    management call over the whole book — what an executive summary is for, rather than
    each product's growth rate restated in turn. And every overall column is then given
    the portfolio lines only IT can make (per-product stances, the shape of the book,
    where it is deep and thin).

    The extras matter as much as the stance: the claim ledger keeps a claim off a second
    page, so a deck drawing on a small pool leaves its later columns thin. The answer is a
    BIGGER pool of distinct claims, not a looser ledger — these are appended after the
    column's own points, so they are reached exactly when the leading claims are spoken
    for, and a column ends up full rather than down to one line.
    """
    from studio.template_fill.stance import portfolio_posture_point

    out = list(said)
    if topic == _STANCE_TOPIC:
        stance = portfolio_posture_point(result)
        if stance:
            out = [stance] + out
    if extras is not None:
        out += [line for line in extras.for_topic(topic) if line not in out]
    return out


def _portfolio_extras(result):
    """The run's extra portfolio claims, loaded ONCE for every column that draws on them."""
    from studio.template_fill.stance import portfolio_extras

    return portfolio_extras(result)


def _survey_pointer(template: Template, result) -> Tuple[Set[int], str]:
    """``({slide indices that carry the survey score tile}, the survey sentence)``.

    The line goes on the page that REPORTS the score, found the same way the tile itself is
    — by its caption — so it follows the tile if the author moves it, and a template with no
    tile (the product and country decks) gets no line. Empty on a premium-basis run.
    """
    from studio.template_fill.survey import kpi, pointer

    tiles = kpi.tiles(template)
    if not tiles:
        return set(), ""
    line = pointer.overall_point(result) or ""
    return {int(t.split(":", 1)[0]) for t in tiles}, line


def values(template: Template, result, *, ledger=None,
           narratives: Optional[List[Any]] = None) -> Dict[str, Any]:
    """``{note-role: bullet list}`` for every commentary prose box in the deck.

    Each value is newline-separated — one bullet per line; the fill engine turns each line
    into its own bulleted paragraph.

    With a ledger, each column takes its points through it: the highlights page, the
    trading summary and the ranking page all describe the same book and each composed the
    same opening sentence, so without one claim landed on four slides.
    """
    out: Dict[str, Any] = {}
    targets = _prose_targets(template)
    if not targets:
        return out
    style = getattr(result, "style", "balanced")
    subject = str(getattr(result, "subject", "") or "")
    facts = panel_facts(result)                 # loaded once; every topic reads the same book
    survey_slides, survey_line = _survey_pointer(template, result)
    extras = _portfolio_extras(result)
    # Keyed by TOPIC, not by topic-and-slide. A topic heading a column on two pages is the
    # template asking the same question twice, and answering it twice from one shrinking
    # pool of claims is worse than answering it once: measured over the shipped templates,
    # splitting the cache per slide raised repeated sentences rather than lowering them,
    # because each new consumer drained the pool until the ledger's keep-one floor had to
    # repeat a claim. One answer per question, and the ledger keeps it off other pages.
    #
    # The ONE exception is the survey line, which belongs to a page rather than a topic —
    # so the key carries whether this column is the one that gets it.
    cache: Dict[Tuple[str, bool], str] = {}
    for t in targets:
        topic = t["topic"]
        wants_survey = bool(survey_line) and t["slide_idx"] in survey_slides
        key = (topic, wants_survey)
        if key not in cache:
            try:
                said = _topic_points(result, topic, facts)
                said = _with_portfolio_stance(said, topic, result, extras)
                if wants_survey:
                    said = list(said) + [survey_line]
                if ledger is not None:
                    said = ledger.take(said, limit=min(len(said), _MAX_COLUMN_BULLETS))
                else:
                    said = said[:_MAX_COLUMN_BULLETS]
                # Trimmed to the column FIRST, then varied: which bullets survive decides
                # which of them still names the carrier, so varying before the ledger has
                # chosen would introduce "the book" with no introduction in front of it.
                said = openings.vary_openings(said, subject)
                base = bullet_list(said)
                cache[key] = _rewrite(base, node=f"commentary-{topic}", style=style,
                                      topic=topic, subject=subject,
                                      facts=facts) if base else ""
            except Exception as exc:  # noqa: BLE001 — commentary must never break the doc
                logger.warning("commentary: topic %s failed: %s", topic, exc)
                cache[key] = ""
        if cache[key]:
            out[_role(t["slide_idx"], t["shape_id"])] = cache[key]
    if narratives is not None:
        narratives.extend(_page_narratives(targets, result, facts))
    logger.info("commentary: filled %d prose box(es) across %d topic(s)", len(out), len(cache))
    return out
