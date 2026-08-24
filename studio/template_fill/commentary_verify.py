"""Two verifiers over written commentary — one deterministic, one a model.

They catch different failures, and neither alone is enough.

The DETERMINISTIC one (:func:`check_numbers`) asks whether every figure in a sentence
appears in the evidence it cites. It is exact, free, and blind to meaning: "Zurich is the
market leader" carries no number at all and sails through, as does "share of wallet rose,
so appetite is clearly there" — an inference premium data cannot make.

The MODEL one (:func:`check_claims`) asks the question a regex cannot: is this claim
supported by the cited facts, and does it use ICG's terms the way ICG defines them
(:mod:`core.definitions`)? It reads the evidence, the glossary, and the sentence, and
returns a verdict per bullet.

Order matters and is not negotiable: deterministic first. It is free and it removes the
worst failure (an invented figure) before a second model ever sees the text, so a model
judging a hallucinated number is a case that cannot arise. The model verifier then runs on
text already known to be numerically sound and rules only on meaning.

Both are DROP-ONLY. Neither may rewrite a sentence — a verifier that edits is a second
author, and then nothing has verified the edit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Judged:
    """One bullet and what the verifiers made of it."""

    text: str
    fact_ids: Tuple[str, ...] = ()
    kept: bool = True
    reason: str = ""


@dataclass(frozen=True)
class Verdict:
    """The outcome over one column."""

    judged: Tuple[Judged, ...] = ()

    @property
    def kept(self) -> Tuple[str, ...]:
        return tuple(j.text for j in self.judged if j.kept)

    @property
    def dropped(self) -> Tuple[Judged, ...]:
        return tuple(j for j in self.judged if not j.kept)

    def log(self, node: str) -> None:
        for j in self.dropped:
            logger.info("commentary_verify: %s dropped %.60r — %s", node, j.text, j.reason)


def check_numbers(judged: Sequence[Judged], pack) -> Verdict:
    """Drop any bullet carrying a figure its CITED facts do not contain.

    Scoped to the cited facts rather than the whole pack, which is the point of citing:
    a sentence that quotes the peer average while citing only the carrier's own premium is
    reaching for a fact it did not claim to be using, and that is how two figures get
    silently swapped.

    A bullet citing NOTHING is checked against the whole pack — a qualitative line
    ("the task here is defending a lead") is legitimate and cites nothing by nature.
    """
    from studio.ai.verifier import allowed_numbers, verify_bullets

    out: List[Judged] = []
    for item in judged:
        sources = pack.rendered_values(item.fact_ids) if item.fact_ids else \
            pack.rendered_values()
        allowed = allowed_numbers(*sources)
        clean, issues = verify_bullets([item.text], allowed)
        if clean:
            out.append(item)
        else:
            out.append(Judged(item.text, item.fact_ids, kept=False,
                              reason=f"unsupported figure ({'; '.join(issues[:2])})"))
    return Verdict(tuple(out))


# ── the model verifier ───────────────────────────────────────────────────────

_JUDGE_SYSTEM = (
    "You verify commentary written for a carrier's quarterly business review. You are given "
    "the EVIDENCE the writer was allowed to use, the ICG DEFINITIONS of the business terms, "
    "and the SENTENCES written. For each sentence decide whether to KEEP or DROP it.\n\n"
    "DROP a sentence when any of these is true:\n"
    "1. It makes a claim the evidence does not support — including a comparison, a cause, a "
    "trend or a consequence that no listed fact establishes.\n"
    "2. It uses a defined term to mean something other than its definition — calling share "
    "of wallet 'market share', calling a Marsh-book rank a 'market rank', calling headroom "
    "'addressable', or inferring appetite from premium.\n"
    "3. It names an individual peer carrier, or reveals one peer's premium, share or rank. "
    "Naming Marsh is fine; naming the subject carrier is fine.\n"
    "4. It asserts something about renewals, retention, rate, loss ratio, capacity or "
    "underwriting appetite that the evidence does not contain.\n\n"
    "KEEP a sentence that is supported, correctly termed, and safe — including one that is "
    "merely a judgement ('the task here is defending a lead') when the judgement follows "
    "from the evidence. Do not drop a sentence for style, length or tone; another check "
    "owns that. When in doubt, KEEP: dropping a good line leaves the page thinner than "
    "keeping a dull one.\n"
    "Return one verdict per sentence, in the order given, with a short reason for each DROP."
)


def _judge_payload(judged: Sequence[Judged], pack, glossary_brief: str) -> str:
    lines = ["EVIDENCE (the only facts the writer could use):", pack.as_brief(), ""]
    if glossary_brief:
        lines += ["ICG DEFINITIONS:", glossary_brief, ""]
    lines.append("SENTENCES:")
    for i, item in enumerate(judged, start=1):
        cites = f"  [cites: {', '.join(item.fact_ids)}]" if item.fact_ids else ""
        lines.append(f"{i}. {item.text}{cites}")
    return "\n".join(lines)


def check_claims(judged: Sequence[Judged], pack, *, glossary_brief: str = "",
                 node: str = "commentary") -> Verdict:
    """Ask a model whether each bullet is supported and correctly termed.

    Returns the input UNCHANGED when the model is unavailable or answers with a verdict
    list that does not line up with the sentences — an unusable answer must not be read as
    "drop everything", which would blank the page.
    """
    from studio.ai import client
    from studio.ai.models import CommentaryVerdicts

    items = list(judged)
    if not items:
        return Verdict(())
    report = client.structured(
        CommentaryVerdicts, _JUDGE_SYSTEM,
        _judge_payload(items, pack, glossary_brief), node=f"{node}-verify")
    if report is None or len(report.verdicts) != len(items):
        if report is not None:
            logger.info("commentary_verify: %s judge returned %d verdict(s) for %d "
                        "sentence(s) — keeping them all", node,
                        len(report.verdicts), len(items))
        return Verdict(tuple(items))
    out: List[Judged] = []
    for item, verdict in zip(items, report.verdicts):
        if verdict.keep:
            out.append(item)
        else:
            out.append(Judged(item.text, item.fact_ids, kept=False,
                              reason=f"unsupported claim ({verdict.reason.strip()})"))
    return Verdict(tuple(out))


def verify(judged: Sequence[Judged], pack, *, glossary_brief: str = "",
           use_agent: bool = True, node: str = "commentary") -> Verdict:
    """Both verifiers, cheapest first. The model only ever sees numerically sound text."""
    numeric = check_numbers(judged, pack)
    numeric.log(node)
    survivors = [j for j in numeric.judged if j.kept]
    if not use_agent or not survivors:
        return numeric
    claims = check_claims(survivors, pack, glossary_brief=glossary_brief, node=node)
    claims.log(node)
    # Both verdicts, in the original order, so the caller can see every drop and why.
    by_text = {j.text: j for j in claims.judged}
    return Verdict(tuple(by_text.get(j.text, j) for j in numeric.judged))
