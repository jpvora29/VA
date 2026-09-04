"""The ICG analysis rules the chatbot answers under, rendered for the writer.

``studio/rules/rules.yaml`` is the signed-off decision tree for this product: when
a growth figure is worth reporting, how small a book has to be before its
percentages stop meaning anything, what counts as material. The deck has obeyed
it since it was written. **The chatbot never read it**, which is why a chat answer
would happily lead on "premium up 1,140%" off a book that wrote forty thousand
dollars last year — a true number and a worthless sentence.

This module is the bridge. The thresholds come from that one file so the two
products cannot drift apart; what is added here is the *framing* an Insurer
Consulting Group answer needs and a threshold cannot express:

* **Marsh is a broker, not a carrier.** The GPR table is premium Marsh PLACED. A
  carrier reading it wants to know the size of the flow it could compete for, so
  the Marsh figure is an opportunity, never a rival's book.
* **Carriers penetrate by industry, not by product line.** Nobody writes "all of
  Property". A useful opening names the industry inside the product.
* **Performance is premium AND perception.** A carrier asking how it is doing is
  asking both; answering with only one is half an answer.

Layering note: ``studio.rules`` is imported lazily and behind a fallback. The
chatbot must not gain a hard dependency on the deck app to answer a question, and
the rules engine already carries defaults equal to the YAML — so a missing file
costs the exact thresholds, never the answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AnalysisThresholds:
    """The numbers a chat answer is judged against, as the writer needs them.

    Mirrors the ``yoy`` and ``materiality`` blocks of ``rules.yaml``; the defaults
    match that file so behaviour is unchanged when it cannot be read.
    """

    yoy_premium_floor: float = 1_000_000.0
    high_growth_pct: float = 100.0
    material_segment_premium: float = 5_000_000.0
    min_share_of_portfolio_pct: float = 3.0

    @property
    def yoy_floor_text(self) -> str:
        return _money(self.yoy_premium_floor)

    @property
    def segment_floor_text(self) -> str:
        return _money(self.material_segment_premium)


def _money(value: float) -> str:
    """A threshold as a person would say it: 1000000 -> '$1M'."""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.0f}bn"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.0f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:.0f}"


def load_thresholds() -> AnalysisThresholds:
    """The thresholds from ``rules.yaml``, or the equal defaults if it is absent."""
    try:
        from studio.rules import load_rules

        cfg = load_rules()
    except Exception as exc:  # noqa: BLE001 - the answer matters more than the exact number
        logger.debug("analysis rules unavailable, using defaults: %s", exc)
        return AnalysisThresholds()
    return AnalysisThresholds(
        yoy_premium_floor=float(cfg.yoy.suppress_if_current_premium_below),
        high_growth_pct=float(cfg.yoy.high_growth_pct),
        material_segment_premium=float(cfg.materiality.min_premium_for_industry_commentary),
        min_share_of_portfolio_pct=float(cfg.materiality.min_share_of_portfolio_pct),
    )


# ── the directives, one concern each ─────────────────────────────────────────

def yoy_directive(t: AnalysisThresholds) -> str:
    """Growth is reported with the money behind it, or not reported."""
    return (
        "[GROWTH AND YEAR-ON-YEAR]\n"
        "- NEVER give a growth percentage on its own. Every YoY figure is stated with "
        "BOTH years' premium, so the reader sees what moved and from what "
        '("$12.4M, up from $11.1M — 12%"). A percentage without its money is not a '
        "finding.\n"
        f"- A percentage off a small base is arithmetic, not insight. Where the current "
        f"book is under {t.yoy_floor_text}, do NOT lead on its growth rate — say the "
        f"premium and, if it matters, that the book is too small for the percentage to "
        f"mean much. A 1,000% rise on a book that wrote almost nothing last year is "
        f"noise, and reporting it as a headline is the fastest way to lose the room.\n"
        f"- Growth above {t.high_growth_pct:.0f}% is only worth leading on when the book "
        f"clears that floor AND you can say what drove it."
    )


def materiality_directive(t: AnalysisThresholds) -> str:
    """Small slices do not earn a sentence."""
    return (
        "[WHAT IS WORTH A SENTENCE]\n"
        f"- A segment, industry or product needs at least {t.segment_floor_text} of "
        f"market premium, or {t.min_share_of_portfolio_pct:.0f}% of the portfolio, "
        "before it is worth commentary. Below that, aggregate it or leave it out.\n"
        "- Prefer one quantified finding to three thin ones."
    )


def marsh_directive() -> str:
    """The single most-misread number in this product."""
    return (
        "[MARSH IS A BROKER, NOT A CARRIER]\n"
        "- Marsh does not write insurance and is never a competitor. The premium in this "
        "data is business Marsh PLACED with carriers.\n"
        "- The Marsh book for a slice is therefore the flow the carrier could compete "
        "for: the ADDRESSABLE OPPORTUNITY through this broker. Frame it that way — "
        '"Marsh placed $84M of Property in Singapore; the carrier wrote $12.4M of it, so '
        '$72M went elsewhere" — because what the carrier wants to know is how much more '
        "is available to write.\n"
        "- Never call the Marsh book \"the market\", \"total market premium\" or "
        "\"industry premium\". It is Marsh's flow, and it is a proxy."
    )


def penetration_directive() -> str:
    """How a carrier actually grows into a line of business."""
    return (
        "[HOW A CARRIER ACTUALLY PENETRATES A LINE]\n"
        "- No carrier sets out to write a whole product line. It picks the INDUSTRY "
        "inside that line where its appetite, capacity and pricing already win.\n"
        "- So an opportunity is only actionable at industry level: name the product AND "
        'the industry inside it ("Property within Manufacturing"), with the Marsh premium '
        "available there. \"Grow in Property\" is not advice a carrier can act on."
    )


def holistic_directive() -> str:
    """Performance is what was written and how the carrier is regarded."""
    return (
        "[A PERFORMANCE QUESTION HAS TWO HALVES]\n"
        "- When the question is about how a carrier is PERFORMING, doing, or positioned, "
        "answer with premium AND the broker-survey score. Volume says what was written; "
        "the survey says whether brokers want to place with them next year.\n"
        "- Where the two disagree — premium up while the score slips, or a strong score on "
        "a shrinking book — say so. That disagreement is usually the most useful sentence "
        "on the page."
    )


def icg_identity() -> str:
    """Who is answering, and for whom."""
    return (
        "[WHO YOU ARE]\n"
        "You are an analyst in Marsh's Insurer Consulting Group. Your client is the "
        "CARRIER, and you advise them on their book placed through Marsh: where it grew, "
        "where it is losing ground, and where the unwritten premium sits. Write for an "
        "underwriting executive who knows the market — plainly, quantified, no hedging, "
        "and never explaining what a percentage is."
    )


#: Ordered so the answer is shaped before it is constrained: who is writing, then
#: the two domain facts most often got wrong, then the numeric bars.
_DIRECTIVES = (
    lambda t: icg_identity(),
    lambda t: marsh_directive(),
    lambda t: penetration_directive(),
    lambda t: holistic_directive(),
    yoy_directive,
    materiality_directive,
)


def analysis_directives(thresholds: Optional[AnalysisThresholds] = None) -> str:
    """Every ICG analysis rule as one prompt block."""
    t = thresholds or load_thresholds()
    return "\n\n".join(render(t) for render in _DIRECTIVES)


#: Stamped on a signature whose instructions already carry the rules, so wiring
#: the same node twice cannot append them twice.
_APPLIED = "_icg_analysis_rules_applied"


def with_analysis_rules(signature: Any) -> Any:
    """Append the ICG analysis rules to a signature's instructions, once.

    The deterministic rails ask for their prose through a
    :class:`core.llm.signature.Signature`, whose class docstring IS the prompt.
    Appending here rather than editing each docstring keeps the thresholds in
    ``rules.yaml`` — a number written into a docstring is a number that drifts.

    Idempotent, and returns the signature either way so it can wrap a class
    inline at the point of use.
    """
    if getattr(signature, _APPLIED, False):
        return signature
    try:
        signature.instructions = (
            f"{getattr(signature, 'instructions', '') or ''}\n\n{analysis_directives()}"
        ).strip()
        setattr(signature, _APPLIED, True)
    except Exception as exc:  # noqa: BLE001 - a node must still answer without them
        logger.warning("could not apply analysis rules to %r: %s", signature, exc)
    return signature


# ── the deterministic half ───────────────────────────────────────────────────

def yoy_is_reportable(
    current_premium: Optional[float],
    growth_pct: Optional[float] = None,
    thresholds: Optional[AnalysisThresholds] = None,
) -> bool:
    """Whether a YoY figure is worth putting in front of a carrier.

    The rule a prompt cannot be trusted with alone: a book below the floor has a
    growth rate that is real and meaningless, and the bigger the percentage the
    more tempting it is to lead on. Callers that HAVE the premium should ask this
    rather than hoping the model remembered.
    """
    t = thresholds or load_thresholds()
    if current_premium is None:
        return True          # nothing to judge on; the prompt rules still apply
    try:
        premium = float(current_premium)
    except (TypeError, ValueError):
        return True
    if premium < t.yoy_premium_floor:
        return False
    if growth_pct is None:
        return True
    try:
        return abs(float(growth_pct)) < t.high_growth_pct or premium >= t.yoy_premium_floor
    except (TypeError, ValueError):
        return True
