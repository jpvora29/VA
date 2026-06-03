"""dspy signature for the follow-up suggestion node.

Runs at the end of the chat workflow with full turn context (question, route,
final answer, and the SQL evidence) so the suggestions are grounded in what the
user actually just saw.
"""
from __future__ import annotations

from typing import List

import dspy


class FollowupSignature(dspy.Signature):
    """
    ROLE:
    You anticipate the NEXT questions a business user would naturally ask after
    reading an insurance analytics answer.

    OBJECTIVE:
    Propose exactly THREE short, self-contained follow-up questions that build on
    the answer just given — drilling deeper, comparing, or widening the lens.

    DOMAIN:
    Insurance premium, Share of Wallet, Share of Portfolio (formerly "appetite"),
    broker survey scores/NPS, peer benchmarks, and market composite rate. Stay
    strictly inside this domain.

    RULES:
    - Each question must be standalone (it will be sent verbatim as a new query),
      end with a question mark, and stay under ~140 characters.
    - Do not repeat or merely rephrase the original question.
    - Ground suggestions in the answer and evidence — do not invent metrics,
      products, or peers that are not implied by the data.
    - Never reference individual peer names; refer to peers only in aggregate.
    - Prefer a mix: one drill-down, one comparison, one trend/time question.
    """

    user_query: str = dspy.InputField(
        desc="The user's question that was just answered."
    )
    route: str = dspy.InputField(
        desc="Which data lens answered it: survey, premium, both, or fallback."
    )
    answer: str = dspy.InputField(desc="The final answer text shown to the user.")
    evidence: str = dspy.InputField(
        desc="Compact summary of the SQL result rows / analytical plan used."
    )
    followups: List[str] = dspy.OutputField(
        desc="Exactly three concise, domain-relevant follow-up questions."
    )
