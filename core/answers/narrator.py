"""The model adapter that writes the answer. One call, prose out.

The division of labour, and why it is where it is:

    the application   decides what is TRUE  — every value, every calculation
    the writer        decides what is SAID  — the order, the words, the shape

:mod:`core.answers.narration` builds the brief and checks the result, so this
module is only the edge: a system prompt, one invoke, a string back. Everything
that could be tested without credentials lives on the other side of it.

The system prompt is the per-question OUTPUT CONTRACT from
:mod:`core.agents.common.answer_shape` — a lookup, a driver question and a "where
should we grow" get three genuinely different answers — under one grounding rule
that no contract may soften: the numbers come from the brief.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.agents.common.answer_shape import shape_contract
from core.answers.narration import NarrationBrief

#: The rule that makes an AI-written answer safe to show. It is stated before the
#: shape contract, and again after it, because it is the one instruction a model
#: asked to "write freely" is most likely to drift from.
GROUNDING = """You are the analyst writing the answer a reader sees.

The application has already queried the data and calculated everything. You are
given VERIFIED FINDINGS (statements it proved, with the calculation behind each)
and FIGURES YOU MAY QUOTE (the values it read back). Your job is to turn that
into the answer to the question — in your own words, in the order that answers
it best.

[THE ONE RULE — every number you write must be copied from the brief]
- Quote figures exactly as the brief renders them. Never round, rescale,
  re-derive or combine them into a number the brief does not contain.
- Never calculate. No sums, differences, percentages, shares or growth rates of
  your own — if it is not in the brief, it is not in the answer.
- A sentence carrying a number the brief does not support is deleted before the
  reader sees it, taking whatever you were arguing with it. Write from the brief.
- You may interpret freely: what the movement means, what it implies, what to
  watch, what the evidence does NOT settle. Judgement is yours; arithmetic is not.

[WHAT THE BRIEF'S FIELDS MEAN]
- `verified_findings` — the argument, strongest first. Use the ones that answer
  the question; ignore the rest rather than listing them all.
- `figures_you_may_quote` — the raw evidence, for detail and for a table.
- `already_on_screen_as_filters` — the reader can see these as chips beside your
  answer. Do not restate them in every sentence.
- `minimum_the_answer_must_convey` — the plain version. Your answer must carry
  its headline figure; everything else about it is yours to improve on.
- `period_chosen_because_the_question_named_none` — when this is set, the reader
  did not say WHICH period and the application picked the latest one in the data.
  Say so once, in the opening sentence, naming the period ("in 2025, the latest
  year in the data"). A figure for one year read as though it were the whole book
  is the error this line exists to prevent. When it is empty, say nothing about
  it — the reader chose the period themselves."""

_CLOSING = """Write the answer now, as Markdown, following the OUTPUT CONTRACT
above. No preamble, no sign-off, no "based on the data". Every number copied from
the brief."""


#: The run tag `core.streaming.TokenStreamHandler` forwards to the live draft.
#: This is the call whose tokens ARE the answer, so it is the only one that
#: streams — the claim selector's tool call and every solver stay silent.
STREAM_TAG = "final_answer"


@dataclass(frozen=True)
class AnswerNarrator:
    """Writes one answer from one brief. The whole LLM boundary for chat prose."""

    client: Any

    def __call__(self, brief: NarrationBrief) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = self._streaming().invoke([
            SystemMessage(content="\n\n".join(
                [GROUNDING, shape_contract(brief.shape), _CLOSING])),
            HumanMessage(content=json.dumps(brief.as_payload(), ensure_ascii=False)),
        ])
        return str(getattr(response, "content", "") or "")

    def _streaming(self) -> Any:
        """The client, tagged so the reader watches the answer being written.

        A client that cannot be configured — a test double, a stub — is used as
        it is. Streaming is a nicety; the answer is not.
        """
        configure = getattr(self.client, "with_config", None)
        return configure(tags=[STREAM_TAG]) if callable(configure) else self.client
