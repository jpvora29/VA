"""The narrative contract — what one slide's argument IS, whichever engine wrote it.

Three engines compose commentary in this repo and each returns its own shape: the
template-fill composers return bullet strings, the QBR pipeline returns fact-cited
sentences, the screen narrator returns ``{label, text, tone}`` points. That is fine for
RENDERING — a PowerPoint cell and a Dash panel genuinely want different things — but it
left no shared answer to the question a reviewer actually asks: what is this slide
claiming, what evidences it, and what should be done about it?

:class:`SlideNarrative` is that answer. Every engine can produce one, so QA, review screens
and any future exporter read one structure instead of three, and a slide missing its action
or its open question is visible rather than merely short.

Deliberately NOT a rendering format. Populating all seven fields does not mean printing
seven sentences — the deck's own three-sentence limit still governs what reaches a page.
Every field but :attr:`primary_claim` is optional, because a slide that has no honest
implication should carry none rather than a manufactured one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

from studio.posture import Posture


class Confidence(str, Enum):
    """How far the evidence behind a narrative actually reaches."""

    EVIDENCED = "evidenced"        # every claim carries a figure from the deck's own facts
    INFERRED = "inferred"          # a comparison the figures support, not one they state
    UNVALIDATED = "unvalidated"    # needs an input this warehouse does not hold


# The closed set of verbs a recommendation may open with — the posture vocabulary plus the
# ladder's own. A recommendation outside this set is either vague ("grow", "focus",
# "monitor") or claims more evidence than the deck holds ("enter" from an observation).
ACTION_VERBS: Tuple[str, ...] = tuple(p.value for p in Posture) + ("Enter",)


@dataclass(frozen=True)
class SlideNarrative:
    """One slide's argument, engine-independent.

    ``slide_role`` names the job this slide does in the deck ("portfolio thesis",
    "performance assessment", "diagnostic agenda"), which is what stops two slides making
    the same point in different words — see :mod:`studio.template_fill.ledger`.
    """

    slide_role: str
    primary_claim: str
    evidence_fact_ids: Tuple[str, ...] = ()
    interpretation: str = ""
    management_implication: str = ""
    recommended_action: str = ""
    posture: Optional[Posture] = None
    confidence: Confidence = Confidence.EVIDENCED
    open_question: str = ""

    def sentences(self) -> Tuple[str, ...]:
        """The narrative as ordered prose, skipping the parts it does not carry.

        Order is the argument's own: what is true, what it means, what it means for
        management, what to do, and what is still unanswered.
        """
        parts = (self.primary_claim, self.interpretation, self.management_implication,
                 self.recommended_action, self.open_question)
        return tuple(p.strip() for p in parts if (p or "").strip())

    @property
    def action_verb(self) -> str:
        """The verb the recommendation opens with, or ``""`` when it opens with none."""
        action = (self.recommended_action or "").strip()
        return next((v for v in ACTION_VERBS if action.startswith(v)), "")

    def gaps(self) -> Tuple[str, ...]:
        """What this narrative is missing — for QA, never for filling in automatically.

        An unvalidated narrative that names no open question is the failure worth catching:
        it has claimed something the evidence does not reach without saying so.

        Fact-ID traceability is deliberately NOT checked here. Only the pipeline engine
        carries an EvidencePack to cite; the template-fill composers ground every claim in
        the figure it is built from, with no id registry behind it. Reporting that as a gap
        on every page of one engine is noise — :func:`commentary_qa.check_narratives`
        applies it only where some producer has shown it can supply ids.
        """
        missing = []
        if not (self.primary_claim or "").strip():
            missing.append("primary_claim")
        if not (self.recommended_action or "").strip():
            missing.append("recommended_action")
        elif not self.action_verb:
            missing.append("recommended_action_verb")
        if self.confidence is Confidence.UNVALIDATED and not (self.open_question or "").strip():
            missing.append("open_question")
        return tuple(missing)

    def is_complete(self) -> bool:
        return not self.gaps()
