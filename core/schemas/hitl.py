"""HITL (human-in-the-loop) clarification schemas.

A Claude-style inline MCQ clarification: when the chatbot is genuinely unsure
what the user means (an unknown carrier, no resolvable market, two equally
plausible metrics/filters), it pauses and asks ONE multiple-choice question with
an always-available free-text fallback, then resumes on the user's answer.

The decision is intentionally conservative — see `ClarifyDecisionSignature`. The
default is to NOT ask, so a confident turn never gets interrupted (the previous
regex-based depth heuristic over-fired; this must not).

Used by the single clarify gate in the checkpointed main graph
(`core.graph.hitl` clarify_decide -> clarify_gate), which handles both lookup and
analytical turns — the only place an `interrupt()` can be resumed.
"""
from __future__ import annotations

from typing import List, Optional

from core.llm import InputField, OutputField, Signature
from pydantic import BaseModel, Field


class ClarifyOption(BaseModel):
    """One selectable answer in the MCQ card."""

    label: str = Field(description="Short button text the user clicks (the answer value).")
    description: str = Field(
        default="",
        description="Optional one-line gloss explaining what choosing this means.",
    )


class ClarifyQuestion(BaseModel):
    """The MCQ payload rendered as an inline card and carried through `interrupt()`."""

    question: str = Field(description="The single clarifying question to ask the user.")
    header: str = Field(
        default="Quick check",
        description="Very short chip label for the card (e.g. 'Carrier', 'Market').",
    )
    options: List[ClarifyOption] = Field(
        default_factory=list,
        description="2-4 concrete, mutually-exclusive choices grounded in valid values.",
    )
    allow_free_text: bool = Field(
        default=True,
        description="Whether the card also offers a free-text answer box (always true).",
    )


class ClarifyDecision(BaseModel):
    """Whether to ask, and if so what."""

    needs_clarification: bool = Field(
        description="True ONLY when the query genuinely cannot be answered well without asking."
    )
    question: Optional[ClarifyQuestion] = Field(
        default=None,
        description="The MCQ to ask when needs_clarification is true; null otherwise.",
    )
    reason: str = Field(
        default="",
        description="One short sentence on why clarification is or is not needed.",
    )


class ClarifyDecisionSignature(Signature):
    """
    [ROLE]
    You are a conservative clarification gate for an insurance analytics chatbot.
    You decide whether the user's question is too ambiguous to answer well and, if
    so, produce ONE multiple-choice clarifying question. You do NOT answer the
    question.

    [DEFAULT = DO NOT ASK]
    Asking unnecessarily is annoying and worse than making a sensible assumption.
    Set needs_clarification = false for the vast majority of turns. Only ask when
    a REQUIRED entity is genuinely missing or unresolvable AND cannot be inherited
    from prior turns (the RoutingContext already carries inherited filters).

    [ASK ONLY WHEN — any of these clearly holds]
    1. The query names a carrier/competitor that does NOT match any valid carrier
       or carrier group (not a near-typo of one) — so you cannot tell who is meant.
    2. The query needs a market/country to be answerable, none is stated, none is
       inherited, and you cannot reasonably default to one.
    3. A term maps to two genuinely different metrics/filters with no way to choose
       (e.g. an ambiguous product/segment word matching multiple valid values).
    4. Inherited filters conflict with the current query in a way you cannot resolve.

    [DO NOT ASK WHEN]
    - A valid carrier/country/metric is named or is inherited (RoutingContext).
    - The query is a normal analytical ask ("how is X doing", "compare", "by
      product/industry/segment") with resolvable entities — just answer it.
    - You could pick an obvious default. Prefer answering with a stated assumption
      over interrupting.

    [WHEN YOU DO ASK]
    - The question MUST name the specific unresolved entity — never a generic
      "Could you clarify?". Quote the user's ambiguous term and state the choice.
      Good: "Did you mean carrier 'Allianz' or 'Allianz Trade'?"
      Good: "Which market — Germany, France, or Italy?"
      Bad:  "Could you clarify what you mean?" / "Can you provide more detail?"
    - You MUST supply 2-4 concrete options drawn from the VALID VALUES provided
      (never invented), mutually exclusive and grounded (e.g. the actual valid
      carriers the typo could match, or the candidate countries/products).
    - If you cannot produce at least 2 grounded options from the valid values,
      DO NOT ASK — set needs_clarification = false and let the turn proceed on a
      sensible default. A question without real options is worse than none.
    - Header is a 2-12 char chip naming the dimension ("Carrier", "Market",
      "Product"), not a sentence. Keep allow_free_text = true.
    """

    current_user_query: str = InputField(
        desc="The latest user question to assess for genuine ambiguity."
    )
    routing_context: object = InputField(
        desc="The RoutingContext (table_family + inherited carrier/country/year/metric). Inherited filters mean DO NOT ask for them."
    )
    valid_values: dict = InputField(
        desc="Valid carriers, carrier groups, countries, products, and segments for grounding options and detecting unknown entities."
    )
    clarify_decision: ClarifyDecision = OutputField(
        desc="Conservative decision: whether to ask and, if so, the MCQ question grounded in valid values."
    )
