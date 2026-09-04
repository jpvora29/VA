"""Insight-writer agent.

The single, always-on synthesis step. Solvers gather evidence but never write
prose; this node turns ALL gathered evidence into the final Markdown answer,
following the output contract. It is a single non-tool LLM call — what used to be
the monolith's `_synthesize_from_evidence` salvage path, promoted to the normal
path so the answer is always written from clean, complete evidence.
"""
from __future__ import annotations

import logging
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage

from core.agents.analyst.common import digest_evidence
from core.agents.common.analysis_rules import analysis_directives
from core.analysis import get_lens_library
from core.initialization import Initialization
from core.observability import log_event
from core.schemas.analyst_subgraph import Evidence
from logger import get_logger

logger = get_logger(__name__)

_OUTPUT_CONTRACT = """[OUTPUT CONTRACT — your reply is a single Markdown string. You are the deeper,
agentic path: deliver MORE than a templated workflow would — more quantified
findings, more cross-lens synthesis, more genuine "so what". Be richer, not
longer for its own sake.]

Structure (use `### ` H3 headings; emoji prefix optional):

1. LEAD — open with ONE H3 heading that states the headline answer in a glance.
   2-3 lines: the direct answer + headline number + business impact. You may
   title it "📌 Executive Summary", "📌 Bottom Line", "📌 TL;DR", or whatever
   fits the question — but it MUST be the first line (no preamble before it).

2. BODY — then 2-4 H3 sections whose HEADINGS YOU CHOOSE to fit THIS question.
   Do not force a fixed template. Name each section after what the data actually
   shows, e.g. "📉 Rate Adequacy Gap", "🏆 Peer Benchmarking", "🎯 Appetite
   Concentration", "🔄 Retention Risk", "📈 Trend & Momentum", "🧩 Segment Mix",
   "🔍 Why This Is Happening". Each section is real analysis: rank shifts,
   SoW/appetite moves, YoY/QoQ deltas, peer-aggregate gaps, drivers, disconnects
   (e.g. premium up but SoW down = market grew faster). **Bold the critical
   numbers.** Use 📈 📉 ⚠️ ✅ where natural.

   NARRATIVE FUNNEL — order the body sections wide → narrow, like a story an
   insurance leader reads top to bottom: the first section frames the BIG
   PICTURE (whole portfolio / market position), the next narrows to the
   segment, product, or geography DRIVING it, and the last lands the sharpest,
   most specific insight (the anomaly, gap, or whitespace worth acting on).
   Each section should answer the question the previous one raises, and the
   prose should connect them explicitly ("that decline is concentrated in…",
   "which is why…") — never disconnected bullets.

3. RECOMMENDATIONS — one H3 section, 2-4 bullets, each starting with a verb
   (Defend, Grow, Re-price, Exit, Re-underwrite, Target) tied to a finding above.

4. SUPPORTING DATA — final H3 section ("📊 Supporting Data"). ALWAYS include a
   compact Markdown table (top 5-10 rows), one row per entity/period. Format
   premium as currency (e.g. $12.4M); SoW / Appetite / YoY / QoQ as %. Aggregate
   peers into a single "Peer avg" row — never one row per named peer. If the
   answer is a single scalar, still give a small 1-2 row table for context.

STYLE: executive tone, no hedging, no filler, no data-dictionary phrasing; never
repeat the same fact across sections.

[CONFIDENTIALITY — non-negotiable]
- Peers are ALWAYS aggregated. NEVER expose an individual peer/carrier name.
- The evidence is already de-identified: a label like "Peer 1" / "Peer 2" IS the
  anonymised form, not a carrier you may name or describe individually. Roll such
  rows up into one aggregate ("peer average", "the peer set") rather than quoting
  them one by one. It is fine to name Marsh and the carrier the question is about."""


_DIRECT_CONTRACT = """[OUTPUT CONTRACT — the user asked for a DIRECT, short answer.]

Reply with the answer ONLY: one or two sentences of plain prose that state the
headline number and the direct conclusion. **Bold the critical number.**

- NO headings, NO bullet sections, NO recommendations block, NO supporting-data
  table, NO follow-up questions.
- Lead with the answer; add at most one clause of essential context.
- If a comparison is part of the answer, state it inline ("…, about 8% below the
  peer average.").

[CONFIDENTIALITY — non-negotiable]
- Peers are ALWAYS aggregated. NEVER name an individual peer/carrier (Marsh and
  the carrier asked about are fine). A "Peer 1" label in the evidence is the
  anonymised form — aggregate it, do not quote it as an entity."""


def write_insight(
    *,
    question: str,
    route: str,
    synthesis_focus: str,
    evidence: List[Evidence],
    presentation: str = "prose",
    depth: str = "analyst",
) -> str:
    """Synthesize the final Markdown answer from all gathered evidence.

    Returns "" if there is no evidence to write from or the call fails, so the
    caller can fall back to a graceful message.

    The per-turn response contract shapes the call: `presentation` of
    'chart_only'/'table_only' skips synthesis entirely (the UI renders the
    chart/table alone, and we never spend the LLM call), while `depth` of
    'direct' swaps the full analyst template for a one-to-two-sentence answer.
    """
    if not evidence:
        return ""

    # Contract: a chart_only / table_only turn wants no prose at all — return
    # early so the writer's LLM call is never made.
    if presentation in ("chart_only", "table_only"):
        log_event(
            logger,
            "insight_skipped_by_directive",
            node="insight_writer",
            route=route,
            presentation=presentation,
        )
        return ""

    library = get_lens_library()
    focus = synthesis_focus or "Answer the question, then add the context a good analyst would."
    digest = digest_evidence(evidence)

    contract = _DIRECT_CONTRACT if depth == "direct" else _OUTPUT_CONTRACT
    # The signed-off ICG decision tree (studio/rules/rules.yaml) plus the framing a
    # threshold cannot express: Marsh is a broker whose book is the carrier's
    # addressable opportunity, penetration happens by industry inside a product, a
    # performance question wants premium AND perception, and a growth percentage is
    # never reported without the money behind it. The deck has obeyed these since
    # they were written; the chat answer did not, which is how "premium up 1,140%"
    # off a book that wrote nothing last year became a headline.
    system_prompt = f"""You are a proactive insurance strategy analyst. Using ONLY
the evidence gathered below, write the final answer — answering the user's
question and proactively adding the context a good analyst would bring.

{analysis_directives()}

[ANALYST PRINCIPLES]
{library.principles()}

Synthesis focus: {focus}

{contract}"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=(
                "Write the final answer NOW, following the OUTPUT CONTRACT exactly. "
                "Do not ask for more data; use only the evidence below.\n\n"
                f"[EVIDENCE — executed queries and their rows, grouped by lens]\n{digest}\n\n"
                f"[USER QUESTION]\n{question}"
            )
        ),
    ]
    try:
        # Stream so the UI can render the answer token-by-token (the turn's
        # TokenStreamHandler, attached to the run config, forwards every chunk
        # tagged `final_answer`). Accumulate here for the committed state value.
        # A Stop raises out of `.stream()` mid-token; the broad except below turns
        # that into a graceful empty answer while the UI keeps the partial it saw.
        parts: List[str] = []
        # Reason tier: the final synthesis is the turn's highest-value reasoning.
        # The warm tier — this is prose a person reads, not structured output.
        for chunk in Initialization.llm_reason.with_config(
            tags=["final_answer"]
        ).stream(messages):
            parts.append(getattr(chunk, "content", "") or "")
        answer = "".join(parts).strip()
    except Exception as exc:  # noqa: BLE001 - synthesis is best-effort
        log_event(
            logger,
            "insight_writer_error",
            logging.ERROR,
            node="insight_writer",
            route=route,
            error=str(exc),
        )
        return ""

    log_event(
        logger,
        "insight_written",
        node="insight_writer",
        route=route,
        evidence_count=len(evidence),
        answered=bool(answer),
    )
    return answer
