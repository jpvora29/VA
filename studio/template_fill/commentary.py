"""QBR commentary slot binding, writing policy and per-bullet readability checks.

AI authors receive scoped evidence and section-specific findings, then numerical and
semantic verification. Each finding stands alone and clear metric openings are allowed.
The default requires verified AI commentary; explicit auto/off modes retain rule drafts.
Relationship feedback remains a placeholder when premium data cannot support it.
"""
from __future__ import annotations

import re
import html
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from logger import get_logger
from studio.template_fill import rewrites
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Slide, Template
from studio.template_fill.sections import Section, section_of

logger = get_logger(__name__)

#: Bullets are newline-separated within one commentary cell.
NEWLINE = "\n"

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
    "concise": "Normally use one short sentence per bullet. Keep only the decisive comparison. ",
    "balanced": "Use one or two short sentences per bullet, normally at most forty-five words. ",
    "detailed": "Use at most two sentences per bullet, adding the material context or a supported next step. ",
}


def min_lines(wanted: int) -> int:
    """A single material finding is enough; empty output still needs repair."""
    return 1 if wanted > 0 else 0


def ask_lines(wanted: int) -> int:
    return wanted


def _bullet_rules(wanted: int) -> str:
    return (f"Write between one and {max(wanted, 1)} independent bullets in priority order, "
            "ONE BULLET PER LINE. Use fewer when evidence supports fewer useful findings. "
            "Do not add filler or split a single finding to fill the column. "
            "Do not prefix lines with bullet characters or numbers; the slide adds them. ")


_TOPIC_BRIEF: Dict[str, str] = {
    "thesis": "THIS COLUMN: the principal finding about this carrier's performance with Marsh. "
              "State the most material result and its comparison; explain a tradeoff only if evidenced. ",
    "key_messages": "THIS COLUMN: the two or three findings leadership should remember. "
                    "Prioritize the material performance result, competitive position or specific next step. ",
    "challenges": "THIS COLUMN: material premium declines, share losses or benchmark shortfalls. "
                  "Name where each occurs and the comparison. Growth alone is not a challenge. "
                  "Do not infer the cause, a failed renewal or persistence into the future from premium. ",
    "working": "THIS COLUMN: material successes. Distinguish absolute premium growth from share gain. "
               "Name the contributing product, industry or client segment where evidenced. "
               "Matching Marsh growth can be a positive absolute result; describe its relative position accurately. ",
    "growth": "THIS COLUMN: named gaps in Marsh placements that warrant investigation. "
              "Distinguish unplaced-with-this-carrier premium from realistic opportunity. "
              "Benchmark parity is an illustrative scenario, not a forecast. "
              "A specific review of appetite, capacity or placement access is a proposed next step, not a known cause. ",
    "reflections": "THIS COLUMN: material lessons from the reported period. Separate the observed result "
                   "from explanations that still need to be investigated. Do not invent what the team misjudged. ",
    "performance": "THIS COLUMN: what changed in Marsh-placed premium, share or rank, on a clearly defined "
                   "comparison. Identify measured contributors where available; don't invent operational causes. ",
    "priorities": "THIS COLUMN: specific next actions linked to named findings. Name the segment and "
                  "the decision or investigation required. Distinguish recommendations from commitments. "
                  "Do not invent an owner, deadline, achievable premium target or renewal event. ",
    "strengths": "THIS COLUMN: material strengths supported by relative performance or placement evidence. ",
    "weaknesses": "THIS COLUMN: material observed shortfalls in premium, share or benchmark position. "
                  "Do not assume low share reflects poor execution without appetite or objectives evidence. ",
    "opportunities": "THIS COLUMN: observed placement gaps worth assessing. State the benchmark and "
                     "what must be validated before this becomes an opportunity the carrier can pursue. ",
    "threats": "THIS COLUMN: an evidenced emerging risk. A concentration is an exposure, not proof of a future loss. "
               "Do not turn a positive result into a threat merely to fill this column. ",
}

_TOPIC_QUESTIONS: Dict[str, Tuple[str, ...]] = {
    "working": ("What improved, against which comparison?", "Which named segment contributed materially?"),
    "challenges": ("Where did premium or share decline?", "Which benchmark shortfall deserves attention?"),
    "growth": ("Which named segments are absent or below the carrier's own placed average?",
               "Where does share trail the largest-carrier benchmark?", "What needs validation before pursuing the gap?"),
    "key_messages": ("Which findings matter most to leadership?",),
    "priorities": ("What specific review or action follows from the material findings?",),
    "thesis": ("What is the most important supported conclusion?",),
    "performance": ("What changed over comparable periods?", "Which measured contributors explain the movement?"),
    "reflections": ("What did the reported results establish, and what remains uncertain?",),
}

# The families a column LEADS from. ``marsh.`` earns a place in almost every one of
# these: a carrier movement means nothing until it is set against the book it sits in,
# and while ``marsh.yoy`` sat in the demoted block every topic reported a fall in
# isolation and read like a spreadsheet cell with a verb.
_TOPIC_EVIDENCE: Dict[str, Tuple[str, ...]] = {
    "thesis": ("sow.", "carrier.", "marsh.", "rank.", "peer."),
    "key_messages": ("carrier.", "marsh.", "sow.", "peer.", "segment."),
    "performance": ("mover.", "pool.", "trend.", "carrier.", "marsh."),
    "working": ("mover.", "sow.", "segment.", "carrier.", "marsh."),
    "challenges": ("carrier.", "marsh.", "sow.", "peer.", "segment.", "mover."),
    "growth": ("segment.", "headroom", "peer.gap", "share.point_value"),
    "priorities": ("segment.", "peer.gap", "mover.", "share.point_value"),
    "reflections": ("trend.", "mover.", "sow.", "carrier."),
}
_EVIDENCE_ALIAS = {"strengths": "working", "weaknesses": "challenges",
                   "opportunities": "growth", "threats": "challenges"}
_IMPERATIVE_TOPICS = frozenset({"key_messages", "priorities", "growth", "opportunities"})


def evidence_focus(topic: str) -> Tuple[str, ...]:
    return _TOPIC_EVIDENCE.get(_EVIDENCE_ALIAS.get(topic, topic), ())


def _questions_rule(topic: str) -> str:
    questions = _TOPIC_QUESTIONS.get(topic, ())
    return ("Answer only where evidenced; never print a question: "
            + " ".join(questions) + " ") if questions else ""


def _voice_rule(topic: str) -> str:
    if topic in _IMPERATIVE_TOPICS:
        return "Proposed actions must follow from named evidence; distinguish investigation from a confirmed solution. "
    return "Report the finding clearly. An operational cause or future outcome requires separate evidence. "


_VOICE = (
    "You are an experienced Marsh Insurer Consulting Group (ICG) analyst and insurance consulting "
    "leader writing a carrier's QBR. Help the carrier understand its performance with Marsh, "
    "material shortfalls, relative placement position and evidence-supported next steps. "
    "Use direct, natural business English that a stakeholder understands on first reading. "
    "Exercise judgement through selecting and explaining the right finding, not through dramatic language. "
)
# What good looks like, stated as craft rather than as a ban list. The prohibitions that
# survive here are the ones that were being BROKEN; the rest moved into _FAITHFULNESS and
# _DEFINITIONS, which is where the non-negotiable guardrails belong. A prompt whose bulk is
# "do not" spends the model's attention on not tripping rules, and what comes back is
# hedged, clause-stuffed and disconnected — which was the complaint.
_CRAFT = (
    "One POINT per bullet, in one or two short sentences. A point may rest on several facts: "
    "a movement and the book it is measured against belong in one sentence, not two. "
    "Name the carrier, product, industry or client segment and the exact metric. "
    "Set every figure against the comparison that gives it meaning — a premium change next to "
    "the Marsh movement over the same period, a share next to its prior or the benchmark. "
    "Use the two or three figures the point needs; the rest belongs in the chart. "
    "Say 'Marsh-placed premium' or 'share of Marsh placements' with the relevant segment. "
)
_FAITHFULNESS = (
    "Every bullet must cite its supporting fact IDs. Copy numerical display values exactly from those facts; "
    "never recalculate, round or invent figures. Preserve direction and distinguish percentages from percentage points. "
    "Only the subject carrier and Marsh may be named; comparison carriers remain aggregate. "
)
_DEFINITIONS = (
    "Use the supplied ICG definitions and their limitations. Marsh-placed premium is not the carrier's entire "
    "premium or revenue. Share of Marsh placements is not total-market share or portfolio mix. "
    "Premium growth does not establish demand growth, pricing, retention, appetite, profitability or capacity. "
    "A share decline does not necessarily mean premium declined. A benchmark gap is not winnable premium. "
    "Compare the same scope and clearly identified periods. Never infer acceleration by comparing annual YoY with QoQ. "
)
_POINTER = (
    "Lead with the meaningful observed finding. Prefer a current/prior share comparison when available. "
    "Identify the segment by name, never 'the client segment that averaged ...'. "
    "If a necessary name, denominator or comparison is missing, omit that finding and flag the data gap. "
)
# The column is ONE argument, not a list of answers to separate questions. Connectives are
# allowed, but only BACKWARD and never in the opening bullet: `_salvage` ships a column that
# lost lines and `_repair` appends lines written in a later call, so any bullet can end up
# first, and a forward reference would then decode to nothing.
_ARGUMENT = (
    "Write the column as ONE argument in priority order, not as separate answers. "
    "The opening bullet must stand entirely on its own and carry the column's most material point. "
    "Later bullets may refer back to it — 'that decline', 'the same segment', 'against this' — "
    "where the reference genuinely sharpens the point. Never refer FORWARD to a bullet not yet read, "
    "and never use a reference a reader cannot resolve from the bullets above it. "
)

# Observation -> interpretation -> question. The old text said a result 'can stand alone' and
# then told the writer not to force a 'so what', which read as an instruction to stop at the
# number. A consultant's value is the middle step, so it is asked for explicitly here and
# judged on its own bar in commentary_verify (an interpretation must not CONTRADICT the
# evidence; it is not required to be literally present in one fact).
_INTERPRETATION = (
    "Where the evidence supports it, take the bullet past the number: state the observation, "
    "then what it means for this carrier's position with Marsh, then — only where it follows — "
    "the question it raises or the review it warrants. "
    "Mark the shift in certainty with your words. An observation is stated flatly. An interpretation "
    "is offered as a reading of the evidence ('this leaves the carrier...', 'the gap is concentrated in...'). "
    "A cause you cannot measure is asked as a question, never asserted. "
    "Do not pad a bullet that has nothing further to say — a clean observation beats a manufactured 'so what'. "
)
_TENSION = (
    "Explain a divergence when it matters, such as premium growing while share falls. "
    "Use a measured decomposition for contribution; operational causes require operational evidence. "
    "Superlatives such as fastest-growing or largest require a complete relevant comparison and a cited ranking. "
)
# Examples carry more of the voice than the rules do, so they show the SHAPE being asked
# for: facts combined into one point, an interpretation that reads as a reading rather than
# a finding, and a second bullet that refers back to the first.
_EXAMPLES = (
    "STYLE EXAMPLES ONLY; their figures are invented and must never be copied: "
    "Good opening bullet, two facts in one point: 'The carrier's Marsh-placed Services premium fell "
    "16.7% to $10M while Marsh's Services book grew 25%, taking its share from 15.0% to 10.0%.' "
    "Good interpretation: 'That leaves the carrier 8.5 points below the 18.5% average of the three "
    "largest carriers in this scope, on a book where each point of share is worth $1M.' "
    "Good back-reference in a later bullet: 'Most of that share loss sits in Manufacturing, "
    "where placements fell $4M of the $5M decline.' "
    "Good proposed priority: 'Review placement outcomes in Services to establish where share was lost "
    "and whether those accounts remain within appetite.' "
    "Poor, a number with no comparison: 'Marsh-placed premium was $10M in 2025.' "
    "Poor, an unmeasurable cause asserted: 'The decline reflects a narrowing risk appetite.' "
    "Poor: 'The carrier should capture all premium placed elsewhere.' "
)


def _analyst_principles() -> str:
    """Kept as a seam for callers; the QBR policy is self-contained."""
    return ""


def _style_directive(style: Optional[str]) -> str:
    return _STYLE_DIRECTIVE.get((style or "balanced").lower(), _STYLE_DIRECTIVE["balanced"])


def _openings_rule(subject: str) -> str:
    return ("You may start with the metric or the carrier's name. Repeat names where they clarify meaning; "
            "do not replace a clear reference merely to vary the opening. ")


def deck_voice(style: Optional[str], subject: str = "") -> str:
    return (_VOICE + _CRAFT + _INTERPRETATION + _ARGUMENT + _TENSION
            + _FAITHFULNESS + _DEFINITIONS + _POINTER
            + _EXAMPLES + _openings_rule(subject) + _style_directive(style))


def column_rules(topic: str, wanted: int) -> str:
    return (_bullet_rules(wanted) + _TOPIC_BRIEF.get(topic, "")
            + _voice_rule(topic) + _questions_rule(topic))


def top_up_rules(topic: str, remaining: int) -> str:
    return (_top_up_bullet_rules(remaining) + _TOPIC_BRIEF.get(topic, "")
            + _voice_rule(topic) + _questions_rule(topic))


def _top_up_bullet_rules(remaining: int) -> str:
    return (f"Write up to {max(remaining, 1)} additional independent bullet(s), only when supported. "
            "Do not rewrite or repeat the already verified lines. No filler and no leading bullet characters. ")


def _style_system(style: Optional[str], *, topic: str = "", wanted: int = 1,
                  subject: str = "") -> str:
    return deck_voice(style, subject) + column_rules(topic, wanted)


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


def prose_targets(template: Template) -> List[Dict[str, Any]]:
    """:func:`_prose_targets`, for the callers outside this module that COUNT them.

    :mod:`studio.template_fill.commentary_fields` tells Setup how many model calls a scope
    will make before the author waits for them, and counting is not a private concern.
    """
    return _prose_targets(template)


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

# Sentence OPENERS that give a deck away as generated. Unlike the words above these
# are only a tell at the start of a line — "the reason is" mid-sentence is ordinary
# English — so they are matched anchored. Every one of these was a fixed template
# somewhere in this package, which is why a ten-product deck opened ten pages the
# same way; the templates are fixed too (see `stance._STANCE_FORMS`), and this stops
# a model rewrite handing them back.
#
# A partner does not announce the shape of the sentence before writing it. They
# state the finding and let the conclusion follow.
_TEMPLATE_OPENERS = re.compile(
    r"^\s*(?:the\s+(?:call(?:\s+here)?\s+is|book\s+wants|reason\s+is|takeaway\s+is|"
    r"story\s+here\s+is|picture\s+here\s+is|question\s+is)"
    r"|what\s+this\s+means\s+is"
    r"|this\s+(?:suggests|indicates|means)\s+that)\b",
    re.I,
)


def _is_whole_sentence(line: str) -> bool:
    """A finished sentence, not a label or a fragment: it ends in a full stop."""
    return line.rstrip().endswith((".", "?", "!"))


@dataclass(frozen=True)
class _LineRule:
    """One reason a single line is not good enough to ship."""

    name: str
    rejects: Callable[[str], bool]


def _line_rules() -> Tuple[_LineRule, ...]:
    """The per-line quality bar, in the order a line is judged against it.

    Refuse fragments, stock filler and ambiguous or overlong comparisons.
    """
    from studio.template_fill import commentary_metrics

    return (
        _LineRule("fragment", lambda ln: not _is_whole_sentence(ln)),
        _LineRule("ai_tell", lambda ln: _AI_TELLS.search(ln) is not None),
        _LineRule("template_opener", lambda ln: _TEMPLATE_OPENERS.match(ln) is not None),
        _LineRule("unclear_comparison", lambda ln: commentary_metrics.clarity_issue(ln) is not None),
    )


def _keep_lines(lines: Sequence[str], subject: str) -> Tuple[List[str], Dict[str, int]]:
    """The lines worth shipping, and a count of why the others were dropped.

    Judged line by line, in order. Explicit carrier names and metric openings are
    welcome when they make the finding clear.
    """
    rules = _line_rules()
    kept: List[str] = []
    dropped: Dict[str, int] = {}
    for line in lines:
        broken = next((r.name for r in rules if r.rejects(line)), None)
        if broken is not None:
            dropped[broken] = dropped.get(broken, 0) + 1
            continue
        kept.append(line)
    return kept, dropped


#: Backward-compatible salvage floor; one supported finding is accepted on the first pass too.
SALVAGE_FLOOR = 1


@dataclass(frozen=True)
class ColumnJudgement:
    """What the shape/reading gate made of one column: the text, and why lines went.

    The reasons used to be logged and dropped. They are the only thing that can tell a
    repair call what was wrong with its first answer, and the only thing that can turn a
    strict-mode refusal from "this field could not be written" into a sentence someone can
    act on — so they travel with the verdict now.

    So do the surviving `lines`, even when the verdict is a refusal. A column rejected for
    being one line short still HAS its good line, and throwing it away is what made repair
    regenerate the whole field and re-earn ground it had already won.
    """

    text: Optional[str]
    dropped: Mapping[str, int] = field(default_factory=dict)
    lines: Tuple[str, ...] = ()
    wanted: int = 0
    floor: int = 0

    @property
    def kept(self) -> int:
        """How many lines survived. Derived, so it cannot disagree with `lines`."""
        return len(self.lines)

    @property
    def reasons(self) -> Tuple[str, ...]:
        """Why this column did not ship, in the words a writer can use. Empty when it did."""
        if self.text is not None:
            return ()
        out = [f"{name} ({count} line(s))" for name, count in sorted(self.dropped.items())]
        out.append(f"only {self.kept} line(s) survived of the {self.wanted} asked for "
                   f"(the column needs {self.floor or min_lines(self.wanted)})")
        return tuple(out)


def judge_column(lines: Sequence[str], *, wanted: int, node: str,
                 subject: str = "", floor: Optional[int] = None) -> ColumnJudgement:
    """:func:`accept_column`, with the reasons kept. See :class:`ColumnJudgement`."""
    return _judge([html.unescape(_LEADING_BULLET.sub("", ln)).strip() for ln in lines if ln and ln.strip()],
                  wanted=wanted, node=node, subject=subject, floor=floor)


def _accept(lines: List[str], *, wanted: int, node: str, subject: str = "",
            floor: Optional[int] = None) -> Optional[str]:
    """The rewritten bullets worth shipping, or ``None`` to keep the draft."""
    return _judge(lines, wanted=wanted, node=node, subject=subject, floor=floor).text


def _judge(lines: List[str], *, wanted: int, node: str, subject: str = "",
           floor: Optional[int] = None) -> ColumnJudgement:
    """The gate itself: which lines survive, and what happened to the rest.

    **Repairs rather than rejects.** This used to refuse the WHOLE column if any
    one line was a fragment, reached for a generated-sounding phrase, opened on
    the carrier once too often, or read out a measure and its value. With five
    such gates over a deck's worth of columns the practical result was that no
    column ever survived — a build logged ``0/27 column(s) written by the model``
    and every page shipped the deterministic draft, which is exactly the generic,
    list-like prose the voice rules exist to replace.

    The bar itself has not moved: a bad line still never ships. It is applied per
    LINE, so a column with one weak line loses that line instead of losing the
    three good ones with it. Only when too few lines survive to make a column does
    the draft stand.
    """
    # `floor` overrides the rewrite bar for the salvage pass (see `SALVAGE_FLOOR`);
    # everything else about the gate is identical, so a salvaged line has cleared every
    # rule a normal one did.
    floor = min_lines(wanted) if floor is None else floor
    # JUDGE every line the model wrote, THEN take the best `wanted` of the survivors.
    #
    # This used to truncate first, and the order mattered more than it looks: a column
    # asked for two bullets whose first line was a fragment lost that line AND never
    # looked at the third, so an answer that contained two shippable sentences failed the
    # column. Filtering first means a spare candidate can actually cover for a rejected
    # line. Nothing weaker ships — every line still clears every rule, and at most
    # `wanted` of them reach the slide.
    kept, dropped = _keep_lines(lines, subject)
    if len(kept) > wanted:
        logger.info("commentary: %s rewrite returned %d usable line(s) for %d bullet(s) — "
                    "keeping the first %d", node, len(kept), wanted, wanted)
        kept = kept[:wanted]
    if dropped:
        logger.info("commentary: %s dropped %d line(s) (%s)", node, sum(dropped.values()),
                    ", ".join(f"{k}={v}" for k, v in sorted(dropped.items())))
    if len(kept) < floor:
        logger.info("commentary: %s kept only %d of %d line(s), below the floor of %d — "
                    "keeping the deterministic draft", node, len(kept), len(lines), floor)
        # The survivors travel with the refusal: repair tops them up instead of
        # rewriting the field, and the salvage pass can ship them as they stand.
        return ColumnJudgement(None, dropped, tuple(kept), wanted, floor)
    return ColumnJudgement(NEWLINE.join(kept), dropped, tuple(kept), wanted, floor)


def accept_column(lines: Sequence[str], *, wanted: int, node: str,
                  subject: str = "") -> Optional[str]:
    """:func:`_accept`, for the batch writer — the same shape and reading bar.

    A column written one-at-a-time and a column written as part of a section must clear the
    identical gate, or "batched" silently means "held to a lower standard".
    """
    return _accept([_LEADING_BULLET.sub("", ln).strip() for ln in lines if ln and ln.strip()],
                   wanted=wanted, node=node, subject=subject)


# Commentary is the deliverable, not an inner loop. The `fast` tier is the one
# ``core.initialization`` describes as "the mechanical inner-loop nodes" — minimal reasoning
# effort — and asking it for a partner's judgement got a partner's vocabulary over a
# clerk's argument. `balanced` could make the editorial calls the rules above allow (merge
# these two claims, cut that one, lead with the consequence) but it runs at temperature 0,
# and prose written at temperature 0 reads like prose written at temperature 0.
#
# `reason` is what the chat analyst writes its final answer on
# (``core.agents.analyst.insight_writer``), and one of the two tiers that run WARM —
# `core.llm.clients.TIERS` documents them as the ones whose output a person reads as
# prose. A QBR column is exactly that. Faithfulness does not rest on the temperature:
# both verifiers and ``_accept`` rule on what comes back, and the deterministic draft
# stands if any of them refuses.
#
# This constant was previously declared and never passed, so every call took
# ``client.structured``'s own default. Wiring it is half of the change.
_COMMENTARY_TIER = "reason"

# The two verifiers are JUDGEMENTS, not prose: they read a sentence against the evidence
# and return a verdict. That wants determinism, not warmth, so they stay where they were.
_VERIFIER_TIER = "balanced"


def plan_rewrite(text: str, *, node: str, style: Optional[str] = None, topic: str = "",
                 subject: str = "", facts: Optional[Dict[str, Any]] = None):
    """This column as a :class:`~studio.template_fill.rewrites.PendingRewrite`.

    The deterministic draft plus the brief a model needs to better it. Composing a column
    and writing it are separated so a whole deck's writes can go out together — see
    :mod:`studio.template_fill.rewrites` — but the pending object already renders as the
    draft, so a value holding one is never wrong, only not yet improved.

    An empty column has nothing to write, so it comes back as the empty string it was.
    """
    if not text:
        return text
    return rewrites.PendingRewrite(draft=text, node=node, topic=topic, subject=subject,
                                   style=style or "balanced", facts=facts or {})


def write_column(pending) -> str:
    """The column as a model writes it from EVIDENCE, or the deterministic draft.

    ``pending.draft`` is the rule composers' newline-separated bullet list. It is passed
    on as the draft — the claims the composers selected and the order they put them in —
    but the model is given the facts themselves
    (:mod:`studio.template_fill.commentary_evidence`) and the ICG definitions of the terms
    in play (:mod:`core.definitions`), so what comes back is written from the book rather
    than reworded from a sentence.

    Everything the model returns has to survive both verifiers (numbers against cited
    facts, then claims and term use against the evidence and the glossary) and then
    :func:`_accept`, which rules on shape and reading. If any of that refuses it, the
    deterministic draft stands — unless ``COMMENTARY_MODE=ai_required``, where it refuses
    the build instead (:mod:`studio.commentary_mode`).

    **A deck no longer takes this path.** :func:`studio.template_fill.rewrites.write_all`
    writes a whole sub-deck per call (:mod:`studio.template_fill.commentary_batch`), which
    is one round trip where this is one per textbox. This stays because ONE column is still
    a thing you sometimes want — a lone caller through :func:`_rewrite`, a debugging run
    through ``write_all(write=write_column)``, and the tests that pin the per-column gates.
    Both paths clear the same bar; see ``commentary_batch``'s module docstring.
    """
    from studio import commentary_mode as mode
    from studio.ai import client
    from studio.template_fill import commentary_evidence as E
    from studio.template_fill import commentary_writer as W

    text = pending.draft
    topic, subject, style, node = pending.topic, pending.subject, pending.style, pending.node
    draft = tuple(ln for ln in text.splitlines() if ln.strip())
    wanted = len(draft)

    def call() -> Optional[str]:
        pack = E.build_pack(pending.facts or {})
        if not pack.items:                  # nothing to cite — the draft is all we have
            mode.refuse(f"{node} has no citable evidence", retryable=False)
            return None
        write = W.make_writer()
        lines = list(write(W.ColumnRequest(
            topic=topic, pack=pack, draft=draft, subject=subject, style=style or "balanced",
            bullets=wanted, brief=_TOPIC_BRIEF.get(topic, ""),
            voice=_style_system(style, topic=topic, wanted=wanted, subject=subject),
            tier=_COMMENTARY_TIER, focus=evidence_focus(topic),
        )))
        accepted = _accept([_LEADING_BULLET.sub("", ln).strip() for ln in lines],
                           wanted=wanted, node=node, subject=subject)
        if accepted is None:
            mode.refuse(f"{node} was written but did not survive verification",
                        retryable=True)
        return accepted

    if not client.llm_available():
        mode.refuse("no model client is available to write commentary", retryable=True)
        return text
    # Deliberately NOT ``client.run_or_fallback``: it swallows every exception, which is the
    # right contract for a best-effort agent and the wrong one here — it would eat the very
    # refusal ``ai_required`` exists to raise and ship the deterministic draft anyway.
    try:
        written = call()
    except mode.CommentaryUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — in ``auto`` the draft is a valid answer
        logger.warning("commentary: %s failed (%s)", node, exc)
        mode.refuse(f"{node} failed", retryable=True, detail=str(exc))
        written = None
    return written if written is not None else text


def _rewrite(text: str, *, node: str, style: Optional[str] = None, topic: str = "",
             subject: str = "", facts: Optional[Dict[str, Any]] = None) -> str:
    """Plan and write one column on the spot — the un-batched pair, for a lone caller."""
    if not text:
        return text
    return write_column(plan_rewrite(text, node=node, style=style, topic=topic,
                                     subject=subject, facts=facts))


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


def with_ledger(ledger, narratives: Optional[List[Any]] = None, *, defer_rewrites: bool = False):
    """This provider bound to a deck's claim ledger and narrative collector.

    The provider list is uniform ``(template, result)`` callables, so the per-deck ledger
    (:class:`~studio.template_fill.ledger.ClaimLedger`), the list each page's
    :class:`~studio.narrative.SlideNarrative` is appended to, and whether this deck writes
    its columns later are injected here rather than threaded through every provider's
    signature.
    """
    def provider(template: Template, result) -> Dict[str, Any]:
        return values(template, result, ledger=ledger, narratives=narratives,
                      defer_rewrites=defer_rewrites)

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
           narratives: Optional[List[Any]] = None,
           defer_rewrites: bool = False) -> Dict[str, Any]:
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
                # Preserve explicit entity names so each bullet stands on its own.
                base = bullet_list(said)
                cache[key] = plan_rewrite(base, node=f"commentary-{topic}", style=style,
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
    # A caller that says nothing about deferral gets finished prose, as it always did.
    # ``assemble`` says so, and then writes every column in the deck in one batch.
    return out if defer_rewrites else rewrites.write_now(out)
