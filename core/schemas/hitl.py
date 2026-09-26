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
    recommended: bool = Field(
        default=False,
        description=(
            "True on AT MOST ONE option: the reading you would assume if the user "
            "skipped the question. Shown as 'Recommended'."
        ),
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
    why: str = Field(
        default="",
        description=(
            "One short line on why the answer changes the result, e.g. 'Premium "
            "and share of wallet can move in opposite directions.'"
        ),
    )


class ClarifyDecision(BaseModel):
    """Whether to ask, and if so what."""

    needs_clarification: bool = Field(
        description="True ONLY when the query genuinely cannot be answered well without asking."
    )
    question: Optional[ClarifyQuestion] = Field(
        default=None,
        description="Legacy single question. Prefer `questions`.",
    )
    questions: List[ClarifyQuestion] = Field(
        default_factory=list,
        description="The 1-2 questions to ask when needs_clarification is true; empty otherwise.",
    )
    reason: str = Field(
        default="",
        description="One short sentence on why clarification is or is not needed.",
    )


class ClarifyDecisionSignature(Signature):
    """
    [ROLE]
    You are the clarification step of an insurance analytics assistant used by
    ICG business leaders. Like a careful analyst, you ask BEFORE you start when
    the request could honestly mean two materially different things — and you
    stay silent otherwise. You never answer the question yourself.

    [THE TEST — ask only if ALL three hold]
    1. There are two or more plausible readings of the request.
    2. They would produce MATERIALLY different answers (different numbers,
       different entities, different time windows), not just different wording.
    3. Nothing decides between them: not the question, not the RoutingContext
       (which already carries inherited carrier/country/year), not an obvious
       business default.

    [WHAT CONFUSION LOOKS LIKE]
    - ENTITY — a carrier/market/product the user names that matches no valid
      value, or matches several ("Allianz" vs "Allianz Trade").
    - MEANING — a word that maps to different governed measures with different
      answers: "performance" (premium growth vs share of wallet vs broker score)
      only when the rest of the question gives no hint; "biggest" (premium vs
      growth); "market" (the whole market vs the Marsh-placed book).
    - PERIOD — "this year" when the latest year is partial; "last quarter" vs
      year to date; a comparison with no stated base period.
    - COMPARISON BASIS — "compare with peers" when a custom peer set and the
      default peer group would both apply; "growth" vs the market or vs itself.
    - CONFLICT — the question contradicts an inherited filter ("in Germany"
      while the chat has been about France) and it is unclear whether to
      replace or add.
    - VAGUE INTENT — a request too broad to scope ("tell me about the market")
      with no carrier, market or measure to anchor it.

    [DO NOT ASK WHEN]
    - The question is a normal analytical ask with resolvable entities ("how is
      Zurich doing in Canada", "compare AXA with peers", "premium by product").
      "How is X performing" is a PERFORMANCE question — answer it with premium,
      movement and standing; do not ask which metric.
    - An inherited filter answers it, or one reading is clearly the default.
    - You would only be confirming something the user already said.

    [HOW TO ASK — the format a senior analyst would use]
    - At most TWO questions, most important first. One is usually enough.
    - `question`: specific, names the ambiguous term in quotes, ends with "?".
      Good: "By 'performance', do you mean premium growth or broker perception?"
      Bad: "Could you clarify what you mean?"
    - `header`: a 1-2 word chip naming the dimension ("Metric", "Period",
      "Carrier", "Peers", "Scope").
    - `why`: one short line on why the choice changes the answer.
    - `options`: 2-4 concrete, mutually exclusive choices. Entity options MUST
      come from VALID VALUES (never invented). Each has a short `label` and a
      one-line `description` of what choosing it means.
    - Mark exactly one option `recommended` — the reading you would assume if
      the user skipped the question.
    - If you cannot produce 2 grounded options, do not ask.
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
