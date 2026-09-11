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

from dataclasses import dataclass, field, replace
import html
import re
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
    topic: str = ""
    #: observation | interpretation | recommendation — the bar this bullet is judged
    #: against (:class:`studio.ai.models.CommentaryBullet`). Unknown values are treated as
    #: ``observation``, which is the strictest, so a writer that omits it loses nothing it
    #: was entitled to.
    kind: str = "observation"


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


#: The bullet's KIND, written into the sentence instead of into its own schema field.
#: Asking the writer to tag each bullet produced "Observation: The carrier grew 12%." on
#: the slide — the tag is machinery for the verifier and must never be prose. Stripped
#: here because every bullet from both writing paths passes through
#: :func:`check_numbers`, so one strip covers the batch writer and the single-column one.
_KIND_PREFIX = re.compile(
    r"^\s*(?:[\[(]\s*(?:observation|interpretation|recommendation|action|finding)\s*[\])]\s*[:—-]?"
    r"|(?:observation|interpretation|recommendation|action|finding)\s*[:—-])\s*", re.I)


def check_numbers(judged: Sequence[Judged], pack) -> Verdict:
    """Drop any bullet carrying a figure its CITED facts do not contain.

    Scoped to the cited facts rather than the whole pack, which is the point of citing:
    a sentence that quotes the peer average while citing only the carrier's own premium is
    reaching for a fact it did not claim to be using, and that is how two figures get
    silently swapped.

    Qualitative claims and proposed actions also need citations. Evidence-availability
    facts support an honest limitation when a section has no qualifying findings.
    """
    from studio.ai.verifier import allowed_numbers, verify_bullets

    out: List[Judged] = []
    for item in judged:
        item = replace(item, text=_KIND_PREFIX.sub("", html.unescape(item.text).strip()))
        unknown = [fid for fid in item.fact_ids if pack.get(fid) is None]
        if unknown:
            out.append(replace(item, kept=False, reason="unknown citation: " + ", ".join(unknown)))
            continue
        if not item.fact_ids:
            out.append(replace(item, kept=False, reason="claim has no supporting fact IDs"))
            continue
        sources = pack.rendered_values(item.fact_ids) if item.fact_ids else \
            pack.rendered_values()
        allowed = allowed_numbers(*sources)
        clean, issues = verify_bullets([item.text], allowed)
        direction_issue = _direction_issue(item, pack)
        if direction_issue:
            out.append(replace(item, kept=False, reason=direction_issue))
        elif clean:
            out.append(item)
        else:
            out.append(replace(item, kept=False,
                               reason=f"unsupported figure ({'; '.join(issues[:2])})"))
    return Verdict(tuple(out))


def _direction_issue(item: Judged, pack) -> str:
    """Catch a simple reversed movement; mixed comparisons need semantic review."""
    movements = [pack.get(fid) for fid in item.fact_ids]
    signs = {1 if e.value > 0 else -1 if e.value < 0 else 0 for e in movements
             if e is not None and e.unit in {"currency_change", "percent_change", "percentage_point_change"}
             and e.value is not None}
    rising = bool(re.search(r"\b(?:grew|rose|increased)\b", item.text, re.I))
    falling = bool(re.search(r"\b(?:fell|declined|decreased)\b", item.text, re.I))
    if len(signs) == 1 and rising != falling and not re.search(r"\b(?:not|never|no|if|would|could)\b", item.text, re.I):
        if (signs == {-1} and rising) or (signs == {1} and falling):
            return "movement direction contradicts the cited change; preserve increase/decrease"
    return ""


# ── the model verifier ───────────────────────────────────────────────────────

_JUDGE_SYSTEM = (
    "Review QBR commentary as an ICG insurance consulting leader before it reaches a carrier. "
    "Assess each bullet against its CITED EVIDENCE, business definitions and SECTION purpose. "
    "Return one KEEP/DROP verdict for each numbered bullet, in the original order.\n"
    "DROP for factual errors: wrong value, direction, denominator, scope, period, comparison, "
    "unsupported causal explanation, ranking or future outcome. Premium growth is not demand growth; "
    "a share decline does not establish an absolute premium decline. An arithmetic contribution "
    "is not evidence of pricing, retention, renewal, appetite, profitability or service quality. "
    "Do not infer acceleration by comparing quarterly QoQ and annual YoY. A large percentage on "
    "a tiny base needs absolute values and context, not a dramatic headline.\n"
    "DROP for unclear meaning: an unnamed industry/client segment, unexplained average, 'the same book', "
    "ambiguous 'share of a pool', or a sentence joining several metrics without saying whose metrics they are. "
    "A reader must identify the entity, metric and comparison on first reading. Scope and periods may "
    "be supplied by the explicit scope evidence and the slide's reporting context.\n"
    "DROP for wrong section: a positive result alone is not a challenge; an unqualified placement gap "
    "is not a winnable opportunity; a concentration alone does not establish a future loss. "
    "DROP generic advice, empty consequence clauses and unsupported superlatives such as 'fastest-growing'. "
    "DROP a bullet that strings together UNRELATED findings, or so many comparisons that the point is "
    "obscured. Combining RELATED facts into one point is correct and must be kept: a movement and the "
    "book it is measured against, or a share and the benchmark it is short of, belong in one bullet.\n"
    "Bullets are given in the order they will be read. A later bullet MAY refer back to an earlier one "
    "('that decline', 'the same segment'); judge it together with the bullet it refers to and KEEP it "
    "where the reference resolves. DROP a reference that points forward or to nothing.\n"
    "EACH BULLET DECLARES ITS KIND, and the kind sets the bar you judge it against. Judging all three "
    "alike is what makes commentary read like a table with verbs.\n"
    "  OBSERVATION — states what the evidence shows. Value, direction, scope, period and comparison "
    "must be exact and present in the cited facts. This is the strictest bar.\n"
    "  INTERPRETATION — reads meaning into an observation ('this leaves the carrier below the carriers "
    "it competes with', 'the shortfall is concentrated in two industries'). It need NOT appear literally "
    "in any fact. KEEP it where it FOLLOWS FROM the cited evidence and does not contradict it. DROP it "
    "only where the evidence points the other way, where it asserts an unmeasurable cause as established "
    "fact, or where it claims more certainty than the evidence carries. Do not demand a citation for the "
    "meaning itself — only for the figures inside it.\n"
    "  RECOMMENDATION — proposes a review, a decision or a priority following from a named finding. "
    "KEEP it where the finding it rests on is real and cited and the action plainly follows. DROP generic "
    "advice, an action with no named finding behind it, or a proposed outcome stated as achievable.\n"
    "A bullet tagged INTERPRETATION or RECOMMENDATION that in fact only restates an observation adds "
    "nothing: DROP it and say so. Mis-tagging is not a reason to drop on its own — judge the sentence "
    "by what it actually does, and apply the stricter bar when the two disagree.\n"
    "DROP individual peer identities or individual peer financials. The subject carrier and Marsh may be named. "
    "Benchmarks must use the actual definition and count; an average per carrier is not combined share.\n"
    "KEEP a clear, material observation that answers its section, even if it begins with Share, Premium, "
    "or the carrier name, or makes no causal claim. Do not demand an extra consequence or action. "
    "A specific proposed investigation of a supported gap is allowed: asking to review appetite does not "
    "assert that appetite is the cause. Distinguish a recommendation from a proven solution. "
    "An evidenced absence is a placement observation and does not prove a lack of appetite. "
    "When the SUPPORT or the MEANING is uncertain — you cannot tell what is being compared, or the "
    "cited facts do not carry the claim — DROP with a precise repair instruction naming the missing "
    "entity, comparison, evidence or incorrect interpretation. Do not approve to fill space. "
    "But do not DROP merely because a supported bullet reaches past the number, reads as prose rather "
    "than a data point, or draws a conclusion you would have worded differently: the column is meant to "
    "read as an argument by an experienced consultant, and a defensible reading of the cited evidence is "
    "the point of the exercise, not a risk to be edited out."
)


def _judge_payload(judged: Sequence[Judged], pack, glossary_brief: str) -> str:
    from studio.template_fill.commentary import _TOPIC_BRIEF
    lines = ["EVIDENCE (the only facts the writer could use):", pack.as_brief(), ""]
    if glossary_brief:
        lines += ["ICG DEFINITIONS:", glossary_brief, ""]
    lines.append("SENTENCES:")
    for i, item in enumerate(judged, start=1):
        cites = f"  [cites: {', '.join(item.fact_ids)}]" if item.fact_ids else ""
        kind = f"  [kind: {item.kind or 'observation'}]"
        context = f"\nSECTION: {item.topic}. {_TOPIC_BRIEF.get(item.topic, '')}" if item.topic else ""
        lines.append(f"{i}. {item.text}{cites}{kind}{context}")
    return "\n".join(lines)


def check_claims(judged: Sequence[Judged], pack, *, glossary_brief: str = "",
                 node: str = "commentary") -> Verdict:
    """Ask a model whether each bullet is supported and correctly termed.

    Missing or misaligned verdicts cannot approve commentary. The caller repairs the
    affected fields, then fails required-AI exports if verification still cannot finish.
    """
    from studio.ai import client
    from studio.ai.models import CommentaryVerdicts
    from studio.template_fill import commentary

    items = list(judged)
    if not items:
        return Verdict(())
    # Pinned to the deterministic tier, deliberately NOT the warm one the column itself
    # is written on: this call returns a verdict per sentence, and a judge that answers
    # the same evidence differently on two runs is not a judge.
    payload = _judge_payload(items, pack, glossary_brief)

    def ask(attempt: int):
        return client.structured(
            CommentaryVerdicts, _JUDGE_SYSTEM, payload,
            tier=commentary._VERIFIER_TIER,
            node=f"{node}-verify" if attempt == 1 else f"{node}-verify-retry",
            phase="verify")

    # A verdict list that does not line up with the sentences cannot approve anything, so
    # the fallback below drops the whole column — which is the right SAFETY answer and the
    # wrong answer to a transient miscount, because under ai_required it refuses the deck.
    # The judge is asked once more before that verdict stands. Still fail-closed; it just
    # no longer turns one malformed answer into a failed build.
    report = ask(1)
    if report is not None and len(report.verdicts) != len(items):
        logger.info("commentary_verify: %s judge returned %d verdict(s) for %d sentence(s) "
                    "— asking once more", node, len(report.verdicts), len(items))
        report = ask(2)
    if report is None or len(report.verdicts) != len(items):
        if report is not None:
            logger.info("commentary_verify: %s judge returned %d verdict(s) for %d "
                        "sentence(s) — verification unavailable", node,
                        len(report.verdicts), len(items))
        return Verdict(tuple(replace(item, kept=False, reason="semantic verification unavailable or incomplete")
                             for item in items))
    out: List[Judged] = []
    for item, verdict in zip(items, report.verdicts):
        if verdict.keep:
            out.append(item)
        else:
            out.append(replace(item, kept=False,
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
    reviewed = iter(claims.judged)
    return Verdict(tuple(next(reviewed) if j.kept else j for j in numeric.judged))
