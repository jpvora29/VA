"""How an answer is SHAPED — chosen from the question, not from a fixed template.

Every written answer used to come out of the same mould: an executive summary, a
key-insights list, a business interpretation, a recommendations block and a
supporting-data table, in that order, whether the user asked "what was Zurich's
UK premium in 2024?" or "where should we grow next year?". Both got five headings
and a table. The first question deserved one sentence.

That sameness is what makes the assistant read as dull: the reader learns the
template after three turns and starts skimming for the one line that answers
them. A good analyst does the opposite — a lookup gets a number, a "why" gets
ranked drivers, a "should we" gets a position and the case against it.

So the shape is a per-turn decision. Each :class:`AnswerShape` owns one way of
answering and the contract that produces it; :func:`detect_answer_shape` picks one
from the raw question, deterministically. Detection is layered exactly like
:mod:`core.agents.common.directives`: the patterns here run on the raw query and
win, the context-filler LLM fills ``OutputDirectives.shape`` for phrasings they
miss, and "auto" means nothing was detected so the default analyst shape applies.

Adding a way of answering means adding one `AnswerShape` to `_SHAPES` — the
detector, the contract and the writer all read from the same row.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

# Applies to every shape: peer aggregation is a confidentiality rule, not a
# stylistic one, so no shape may drop it.
_CONFIDENTIALITY = """[CONFIDENTIALITY — non-negotiable]
- Peers are ALWAYS aggregated. NEVER name an individual peer/carrier. Marsh and
  the carrier the question is about are fine to name.
- A "Peer 1" / "Peer 2" label in the evidence IS the anonymised form, not a
  carrier you may name or describe one by one. Roll such rows into one aggregate
  ("the peer average", "the peer set")."""

# Also applies to every shape. The reader sees many answers in a session; the
# fastest way to sound like a form letter is to open all of them the same way.
_VARIETY = """[DO NOT SOUND LIKE A TEMPLATE]
- Open with the answer, in whatever words this particular question calls for.
  Never open with a stock phrase ("Here's a breakdown of...", "Based on the
  data...", "Let's dive into...", "It's worth noting that...").
- Only include a section you have something to SAY in. An empty heading is worse
  than a missing one — if there is no real trend, do not write a trend section.
- Say each fact once. A number repeated in a summary, a bullet and a table reads
  as padding three times over.
- Length follows the question. A small question gets a small answer, and that is
  a good answer, not a lazy one."""


# Applies to every shape that asks for a table — which is most of them. The
# shapes said "a compact table" and left the mechanics open, so a table came back
# as bullets, as an ASCII block, or fenced in ``` (which renders as monospace
# text, not a table). A table the reader can scan is the single biggest
# readability win in an answer, so the mechanics are pinned here once.
_TABLES = """[WHEN YOU WRITE A TABLE]
- Use a GitHub Markdown pipe table with a header row AND a separator row. Never
  put a table inside a code fence — fenced text does not render as a table.
- Right-align every numeric column by writing the separator cell as `---:`. Left
  align the label column. A column of figures that is not aligned cannot be
  compared down the page, which is the only reason to use a table.
- At most 6 columns and 10 rows. A table is the shape of the finding, not a data
  dump — the reader has the full result set beside the answer.
- Format consistently down a column: currency as $12.4M, shares and changes as
  19.5% / +6.4pp, and one dash (-) for a value the data does not have. Never mix
  units in one column.
- Say it once. Do not restate a table's numbers in the prose around it — lead
  into the table with what it shows, and follow it with what it means."""


@dataclass(frozen=True)
class AnswerShape:
    """One way of answering, and the phrasings that call for it.

    `contract` is the body of the OUTPUT CONTRACT the writer is handed; the
    shared table, confidentiality and anti-template blocks are appended by
    :func:`shape_contract`, so a shape never restates them.

    `patterns` are matched against the RAW user question, in registry order, so a
    more specific shape declared earlier wins over a looser one below it.
    """

    key: str
    label: str
    contract: str
    patterns: Tuple["re.Pattern[str]", ...] = ()

    def matches(self, question: str) -> bool:
        return any(p.search(question) for p in self.patterns)

    @property
    def allows_table(self) -> bool:
        """True when this shape's own contract asks for a table.

        Read off the contract rather than declared twice: a shape that says "NO
        supporting-data table" must not then be handed the table style guide.
        """
        text = self.contract.lower()
        return "table" in text and "no supporting-data table" not in text


# ── the shapes ───────────────────────────────────────────────────────────────
# Ordered by specificity: the first match wins, so "why is X top of the list"
# reads as a driver question (why) rather than a ranking one (top).

_DIRECT = AnswerShape(
    key="direct",
    label="Direct answer",
    contract="""[SHAPE — DIRECT ANSWER. This is a lookup: the user wants a number, not an essay.]

Reply with one or two sentences of plain prose. **Bold the headline number.**
Add at most one clause of context — the comparison that makes the number mean
something (prior year, the peer average, the share of the book).

NO headings. NO bullets. NO recommendations. NO supporting-data table.
If the honest answer is "the data does not cover that", say so in one sentence.""",
    patterns=(
        re.compile(
            r"^\s*(?:what|how much|how many|how big)\b(?!.*\b(?:why|driv|caus|should|compare)\b)",
            re.IGNORECASE,
        ),
    ),
)

_RANKING = AnswerShape(
    key="ranking",
    label="Ranked list",
    contract="""[SHAPE — RANKING. The list IS the answer; the prose exists to frame it.]

1. ONE opening sentence: who leads, and by how much over second place. If the
   gap is trivial, say the top of the list is effectively tied — that is the
   finding.
2. The ranked table. One row per entity, ordered, with the measure and its share
   of the total. Currency as $12.4M; shares and growth as %. Peers aggregated
   into a single row.
3. ONE closing line: the thing in the ranking a reader would not have guessed —
   a name higher or lower than expected, a long tail, a concentration.

NO recommendations block. NO separate interpretation section — the closing line
carries the read.""",
    patterns=(
        re.compile(
            r"\b(?:top|bottom)\s+\d+\b|\btop\s+(?:five|ten|three)\b"
            r"|\brank(?:ed|ing)?\b|\bleague\s+table\b"
            r"|\bwhich\s+\w+\s+(?:is|are|has|have)\s+the\s+(?:biggest|largest|highest|lowest|smallest|most|least)\b"
            r"|\b(?:biggest|largest|highest|lowest|smallest)\s+\w+\s+(?:by|in)\b",
            re.IGNORECASE,
        ),
    ),
)

_DRIVER = AnswerShape(
    key="driver",
    label="Driver analysis",
    contract="""[SHAPE — DRIVERS. The user asked WHY. Ranked causes are the answer.]

1. State the movement first, quantified and in both directions of the comparison
   ("$12.4M, down from $15.1M — a $2.7M fall").
2. The drivers, RANKED by how much of the movement each explains. For each: the
   slice, its own change in currency, and roughly what share of the total move it
   accounts for. Two or three real drivers beat six thin ones.
3. What it is NOT — rule out the explanation a reader would otherwise assume
   ("this is not a rate story; volume fell across every band"). Only when the
   evidence actually rules something out.
4. Close on the driver that is still moving, and therefore the one that matters
   next quarter.

NO generic recommendations block — the drivers ARE the finding. A compact table
only if the ranked drivers need more than three rows to be legible.""",
    patterns=(
        re.compile(
            r"\bwhy\b|\bwhat\s+(?:drove|caused|is\s+driving|is\s+causing|explains)\b"
            r"|\breasons?\s+(?:for|behind|why)\b|\bdriven\s+by\b"
            r"|\bexplain\s+(?:the|this|why)\b|\bwhat'?s\s+behind\b",
            re.IGNORECASE,
        ),
    ),
)

_COMPARISON = AnswerShape(
    key="comparison",
    label="Comparison",
    contract="""[SHAPE — COMPARISON. Lead with the verdict, then only where they differ.]

1. The verdict in one sentence: who is ahead, on what, and by how much.
2. The contrast, on the TWO OR THREE dimensions where the subjects actually
   differ. Skip anything where they are broadly the same — "both are around 4%"
   is not a comparison, it is filler. Bold each gap.
3. A compact side-by-side table: one row per dimension, one column per subject,
   plus the gap. Peers aggregated into a single column.
4. ONE line on what explains the gap, where the evidence supports it.

NO recommendations block unless the user asked what to do about it.""",
    patterns=(
        re.compile(
            r"\bcompared?\b|\bcomparison\b|\bvs\.?\b|\bversus\b"
            r"|\bagainst\s+(?:peers?|the\s+market|competitors?)\b"
            r"|\brelative\s+to\b|\bbetter\s+or\s+worse\b|\bhow\s+does?\s+\w+\s+stack\b"
            r"|\bahead\s+of\b|\bbehind\b",
            re.IGNORECASE,
        ),
    ),
)

_TREND = AnswerShape(
    key="trend",
    label="Trend",
    contract="""[SHAPE — TREND. Describe the line, not every point on it.]

1. The shape of the series in one sentence: direction, total magnitude over the
   window, and where it turned ("flat through 2022, then up $8M across 2023-24").
2. The periods that MATTER — the inflection, the peak, the latest. Not a
   paragraph per period. Quantify each, and say what changed at the turn.
3. Where the series is heading on current evidence, stated as an observation and
   never as a forecast number you invented.
4. A compact period table (one row per period) only when the series has more than
   three points.

If the window is incomplete (a part-finished quarter or year), say so on the
number rather than comparing it as if it were whole.

NO recommendations block.""",
    patterns=(
        re.compile(
            r"\btrends?\b|\btrending\b|\bover\s+(?:time|the\s+(?:last|past)\s+\w+)\b"
            r"|\bsince\s+(?:19|20)\d{2}\b|\byear[\s-]on[\s-]year\s+trend\b"
            r"|\bhow\s+has|\bhow\s+have\b.*\b(?:changed|grown|moved|evolved|developed)\b"
            r"|\btrajectory\b|\bover\s+the\s+years\b",
            re.IGNORECASE,
        ),
    ),
)

_ADVISORY = AnswerShape(
    key="advisory",
    label="Advisory",
    contract="""[SHAPE — ADVISORY. The user asked what to DO. Take a position.]

1. The recommendation FIRST, in one sentence, as a position — not a menu of
   options and not a restatement of the question.
2. The evidence for it: the two or three quantified findings that make it the
   right call. Name the product AND the industry inside it; "grow in Property" is
   not advice a carrier can act on.
3. The case AGAINST, honestly — what would have to be true for this to be wrong,
   or what the evidence does not cover. An adviser who never states the risk is
   not trusted twice.
4. The moves: 2-4 bullets, each starting with a verb (Defend, Grow, Re-price,
   Exit, Re-underwrite, Target), each tied to a finding above, each with the
   number that sizes it.
5. A compact table sizing the opportunity or the exposure.""",
    patterns=(
        re.compile(
            r"\bshould\s+(?:we|i|they|the\s+\w+)\b|\bwhere\s+should\b|\bwhat\s+should\b"
            r"|\brecommendations?\b|\brecommend\b|\bwhat\s+do\s+(?:we|i)\s+do\b"
            r"|\bwhere\s+(?:can|could)\s+we\s+grow\b|\bworth\s+(?:entering|exiting|pursuing)\b"
            r"|\bopportunit(?:y|ies)\b|\bwhitespace\b|\bstrategy\b|\bprioriti[sz]e\b",
            re.IGNORECASE,
        ),
    ),
)

_BRIEFING = AnswerShape(
    key="briefing",
    label="Briefing",
    contract="""[SHAPE — BRIEFING. Someone is walking into a meeting in five minutes.]

1. THE THREE NUMBERS THAT MATTER — exactly three, each one line: the figure, and
   the single clause that says whether it is good.
2. WHAT CHANGED — the two or three real movements since the comparison period,
   each quantified. Nothing that merely stayed the same.
3. WHAT TO WATCH — one short paragraph or two bullets: the thing most likely to
   come up, and the honest answer to it.

Short sections, scannable, no long prose. NO supporting-data table — this is read
standing up. NO recommendations block unless a decision is genuinely pending.""",
    patterns=(
        re.compile(
            r"\bbrief\s+me\b|\bgive\s+me\s+an?\s+(?:brief|overview|summary|rundown)\b"
            r"|\boverview\s+of\b|\bhow\s+are\s+we\s+doing\b|\bhow\s+is\s+\w+\s+doing\b"
            r"|\bprepare\s+(?:me\s+)?for\b|\bsummari[sz]e\s+(?:the|our|their)\b"
            r"|\btell\s+me\s+about\b|\bwhere\s+do\s+we\s+stand\b",
            re.IGNORECASE,
        ),
    ),
)

_ANALYST = AnswerShape(
    key="analyst",
    label="Full analysis",
    contract="""[SHAPE — FULL ANALYSIS. An open question with room to explore it.]

1. LEAD — one H3 heading stating the headline answer at a glance: the direct
   answer, the headline number, the business consequence. Two or three lines.
   Title it for THIS question, not "Executive Summary" every time.
2. BODY — TWO OR THREE H3 sections, and only ones you have real analysis for.
   Name each after what the data actually shows ("Rate adequacy gap", "Where the
   growth went", "The retention problem underneath"). Order them wide -> narrow:
   the portfolio picture, then the segment driving it, then the sharpest specific
   finding. Connect them explicitly ("that decline is concentrated in..."), so
   each section answers the question the one above it raises. **Bold the critical
   numbers.**
3. SO WHAT — 2-3 bullets, each starting with a verb, each tied to a finding
   above. Include this ONLY when the analysis actually implies action.
4. A compact supporting table (5-10 rows) when the answer rests on more numbers
   than the prose can carry. Skip it when it would only restate the prose.

Three or four sections in total. If you find yourself writing a fifth, you are
padding.""",
)

# Registry order is detection priority. `analyst` carries no patterns: it is the
# default, returned when nothing above it matched.
_SHAPES: Tuple[AnswerShape, ...] = (
    _DRIVER,
    _ADVISORY,
    _BRIEFING,
    _COMPARISON,
    _RANKING,
    _TREND,
    _DIRECT,
    _ANALYST,
)

_BY_KEY = {shape.key: shape for shape in _SHAPES}

#: The shape keys the LLM directive field and the writer accept.
SHAPE_KEYS: Tuple[str, ...] = tuple(_BY_KEY)

DEFAULT_SHAPE = _ANALYST.key


def detect_answer_shape(question: str) -> Optional[str]:
    """The shape this question calls for, or None when no pattern matched.

    Deterministic and zero model calls. None means "no opinion" — the caller
    leaves whatever the LLM read in place, and the default applies if it read
    nothing either.
    """
    text = question or ""
    if not text.strip():
        return None
    for shape in _SHAPES:
        if shape.matches(text):
            return shape.key
    return None


def get_shape(key: Optional[str]) -> AnswerShape:
    """The shape for a key, falling back to the default for auto/unknown/None."""
    return _BY_KEY.get((key or "").strip().lower(), _ANALYST)


def shape_contract(key: Optional[str]) -> str:
    """The full OUTPUT CONTRACT for a shape: its body plus the shared blocks.

    The table block is included only for shapes that actually ask for a table —
    handing table mechanics to a shape that forbids one (a direct lookup, a
    stand-up briefing) is an invitation to write one anyway.
    """
    shape = get_shape(key)
    blocks = [
        "[OUTPUT CONTRACT — your reply is a single Markdown string.]",
        shape.contract,
    ]
    if shape.allows_table:
        blocks.append(_TABLES)
    blocks += [_VARIETY, _CONFIDENTIALITY]
    return "\n\n".join(blocks)


def shape_label(key: Optional[str]) -> str:
    """Human-readable name of a shape, for logs and telemetry."""
    return get_shape(key).label
