"""The brief a writer works from, and the check on what it writes back.

The claim ledger (:mod:`core.answers.claims`, :mod:`core.answers.insights`) is
arithmetic: every sentence in it is true by construction. It is also the same
sentence every time. Read three answers in a session and the reader has learnt
the mould — "X increased from A to B", then the same four bullets — and stops
reading. Correct and unread is not a good answer.

So the ledger stops being the prose and becomes the ARGUMENT: an ordered set of
verified findings, plus every figure the evidence holds, handed to a writer that
shapes them into an answer to the question that was actually asked. The writer
chooses the words, the order, the groups and the table. It does not choose the
numbers.

That is what this module enforces. :func:`verify_narration` re-reads the finished
text against the ledger and drops any line carrying a figure the evidence does
not support, so an invented number cannot survive onto the screen; a narration
that loses the headline figure is rejected whole, and the deterministic ledger is
always there to fall back on.

Pure: dataclasses and strings in, dataclasses and strings out. No model, no
database — so the verifier is unit-testable with planted violations, which is the
only way to trust it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Sequence

from core.answers import figures as fig
from core.answers.claims import AnswerClaim
from core.answers.facts import AnswerFact
from core.answers.scope import DisplayScope

#: How much of the ledger the writer is shown. Past this the brief is padding — a
#: writer that cannot make an answer out of twelve verified findings will not be
#: rescued by a thirteenth.
BRIEF_CLAIMS = 12

#: How many figures ride along as raw material for a table. Generous, because a
#: product-line table is exactly the "missing information" a claim list cannot
#: carry; capped, because a brief is not a data dump.
BRIEF_FIGURES = 80

# A line that is already structure — a heading, a bullet, a numbered point, a
# table row, a quote, a fence — is kept or dropped whole; only a prose paragraph
# is cut sentence by sentence. A numbered point is here rather than in the prose
# path because "1." reads as the end of a sentence, and cutting there leaves a
# bare marker behind when the point itself goes.
_STRUCTURE = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```)")


@dataclass(frozen=True)
class NarrationBrief:
    """Everything the writer may use, and nothing else."""

    question: str
    shape: str
    ledger: str
    claims: tuple[AnswerClaim, ...] = ()
    facts: tuple[AnswerFact, ...] = ()
    scope: DisplayScope = ()
    defaulted_period: str = ""

    def as_payload(self) -> dict:
        """The brief as JSON, in the words the writer's contract uses."""
        return {
            "question": self.question,
            "already_on_screen_as_filters": [{"field": k, "value": v} for k, v in self.scope],
            "verified_findings": [
                {"id": c.id, "statement": c.text, "calculation": c.formula}
                for c in self.claims[:BRIEF_CLAIMS]
            ],
            "figures_you_may_quote": [
                {"measure": f.metric, "value": f.rendered,
                 "where": {k: v for k, v in f.dimensions}}
                for f in self.facts[:BRIEF_FIGURES]
            ],
            "minimum_the_answer_must_convey": self.ledger,
            "period_chosen_because_the_question_named_none": self.defaulted_period,
        }


@dataclass(frozen=True)
class Narration:
    """A written answer after checking, plus what the check took out."""

    text: str = ""
    dropped: tuple[str, ...] = ()
    rejected: str = ""

    @property
    def accepted(self) -> bool:
        return bool(self.text) and not self.rejected


Writer = Callable[[NarrationBrief], str]


def build_brief(question: str, shape: str, ledger: str, claims: Sequence[AnswerClaim],
                facts: Sequence[AnswerFact], scope: DisplayScope = (),
                defaulted_period: str = "") -> NarrationBrief:
    """The brief for one answer, in the order the ledger ranked it."""
    return NarrationBrief(question=question, shape=shape, ledger=ledger,
                          claims=tuple(claims), facts=tuple(facts), scope=tuple(scope),
                          defaulted_period=str(defaulted_period or ""))


def supported_numbers(claims: Sequence[AnswerClaim],
                      facts: Sequence[AnswerFact]) -> frozenset[str]:
    """Every numeric form the writer is allowed to put on the page.

    Both halves of the ledger contribute: the FACTS give the raw values and every
    rounding and scaling a person would write them in, and the CLAIM sentences
    give the derived figures — a growth rate, a share, a gap — that the
    application calculated and no row holds.
    """
    allowed = set(fig.values_in_rows([{f.metric: f.value} for f in facts]))
    for text in [f.rendered for f in facts] + [c.text for c in claims]:
        for figure in fig.figures_in(text):
            allowed |= fig.forms_of(figure.value)
    return frozenset(allowed)


def unsupported_in(text: str, allowed: frozenset[str]) -> list[str]:
    """The figures in one fragment that the ledger does not support.

    Years and small ordinals are not measures (`figures.Figure.is_checkable`), so
    a writer numbering three points does not lose them.
    """
    return [f.text for f in fig.figures_in(text)
            if f.is_checkable and not (fig.forms_of(f.value) & allowed)]


def headline_figures(claims: Sequence[AnswerClaim]) -> frozenset[str]:
    """The figures the direct answer is made of, in every form they can take.

    The lead claim IS the answer to the question, so prose that states none of
    its numbers has changed the subject however well it reads. Any ONE of them is
    enough: a writer may lead on the current value, on the movement or on the
    rate, and which of those best answers the question is the writer's call.
    """
    lead = next(iter(claims), None)
    if lead is None:
        return frozenset()
    return frozenset(form for figure in fig.figures_in(lead.text) if figure.is_checkable
                     for form in fig.forms_of(figure.value))


def split_sentences(line: str) -> list[str]:
    """A prose line split into sentences, keeping the punctuation on each.

    A full stop only ends a sentence when a space or the line follows it, which
    is what keeps "$8.2m" and "19.5%" in one piece.
    """
    out, current = [], ""
    for index, char in enumerate(line):
        current += char
        ends = char in ".!?" and (index + 1 == len(line) or line[index + 1] == " ")
        if ends and current.strip():
            out.append(current.strip())
            current = ""
    if current.strip():
        out.append(current.strip())
    return out


def _keep_prose(line: str, allowed: frozenset[str]) -> tuple[str, list[str]]:
    """A prose line with its unsupported sentences removed."""
    kept, dropped = [], []
    for sentence in split_sentences(line):
        bad = unsupported_in(sentence, allowed)
        if bad:
            dropped.extend(bad)
        else:
            kept.append(sentence)
    return " ".join(kept), dropped


def _keep_line(line: str, allowed: frozenset[str]) -> tuple[str, list[str]]:
    """One markdown line after checking: kept whole, trimmed, or gone."""
    stripped = line.strip()
    if not stripped:
        return line, []
    if _STRUCTURE.match(stripped):
        bad = unsupported_in(stripped, allowed)
        return ("" if bad else line), bad
    return _keep_prose(stripped, allowed)


def _leads_a_group(lines: Sequence[str], index: int) -> bool:
    """Whether anything survives under this heading before the next one."""
    for line in lines[index + 1:]:
        if line.strip().startswith("#"):
            return False
        if line.strip():
            return True
    return False


def _keeps_its_rows(lines: Sequence[str], index: int) -> bool:
    """Whether a table header still has body rows under it."""
    for line in lines[index + 1:]:
        text = line.strip()
        if not text.startswith("|"):
            return False
        if fig.figures_in(text):
            return True
    return False


def _prune(lines: Sequence[str]) -> list[str]:
    """One pass: drop orphan headings, empty tables and doubled blank lines."""
    kept: list[str] = []
    for index, line in enumerate(lines):
        text = line.strip()
        if not text:
            if kept and kept[-1].strip():
                kept.append("")
            continue
        if text.startswith("#") and not _leads_a_group(lines, index):
            continue  # a heading whose whole group was dropped is not a group
        if text.startswith("|") and not fig.figures_in(text) and not _keeps_its_rows(lines, index):
            continue  # a header and separator with nothing left under them
        kept.append(line)
    return kept


def _tidy(lines: Sequence[str]) -> str:
    """Close the gaps a dropped line leaves, until nothing more comes loose.

    One pass is not enough: a heading over a table keeps the heading (its header
    row is still there), and the same pass then drops that header row, leaving
    the orphan the first check exists to prevent. Repeating until the text stops
    changing costs nothing on an answer with nothing to prune.
    """
    kept = list(lines)
    while True:
        pruned = _prune(kept)
        if pruned == kept:
            return "\n".join(pruned).strip()
        kept = pruned


def verify_narration(text: str, brief: NarrationBrief) -> Narration:
    """Drop what the ledger does not support; reject what no longer answers.

    Rejection is not failure — it is the pipeline choosing the deterministic
    ledger, which is always correct and always available. Only a narration that
    survives with its headline figure intact is worth preferring to it.
    """
    if not (text or "").strip():
        return Narration(rejected="empty")
    allowed = supported_numbers(brief.claims, brief.facts)
    checked = [_keep_line(line, allowed) for line in text.splitlines()]
    kept = _tidy([line for line, _ in checked])
    dropped = tuple(dict.fromkeys(item for _, bad in checked for item in bad))
    if not kept:
        return Narration(dropped=dropped, rejected="nothing survived the figure check")
    headline = headline_figures(brief.claims)
    written = {form for figure in fig.figures_in(kept) for form in fig.forms_of(figure.value)}
    if headline and not (headline & written):
        return Narration(dropped=dropped, rejected="the headline figure was lost")
    return Narration(text=kept, dropped=dropped)


def narrate(brief: NarrationBrief, writer: Writer) -> Narration:
    """Ask the writer for an answer and return only a verified one.

    A writer that raises, times out or is not configured is the same outcome as
    one that invents a number: no narration, and the caller keeps the ledger.
    """
    try:
        draft = writer(brief)
    except Exception as error:  # a prose upgrade must never fail an answer
        return Narration(rejected=f"writer unavailable: {type(error).__name__}")
    return verify_narration(str(draft or ""), brief)
