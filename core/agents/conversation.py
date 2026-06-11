"""Conversation meta-intent handler.

Answers turns that are ABOUT the conversation rather than the data — "summarize
our discussion", "what did you recommend earlier?". It reads the persisted
transcript and restates it; it never issues a new database query, so a recap can
never contradict the answers it is summarizing, and a meta turn costs one LLM
call instead of a full analytical run.

The in-graph `messages` channel carries only the user's turns, so the full
transcript (both sides) is loaded from the conversations store via the
thread_id/user_id threaded in from the UI. Output reuses the prose-only
`out_of_scope_answer` rendering path, so no surface-specific UI change is needed.
"""
from __future__ import annotations

import logging
from typing import Any, List

from langchain_core.messages import HumanMessage, SystemMessage

from core.agents.common.meta_intent import conversation_intent_of
from core.initialization import Initialization
from core.observability import log_event
from core.store.conversations import load_conversation
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)

# Bound the transcript handed to the model: the most recent turns carry the most
# relevant decisions, and a runaway history would blow the context budget.
_MAX_TRANSCRIPT_MESSAGES = 40
_MAX_TRANSCRIPT_CHARS = 6000

_EMPTY_TRANSCRIPT = (
    "We haven't covered anything yet in this conversation, so there's nothing to "
    "summarize. Ask a data question to get started and I'll keep track of the "
    "findings and recommendations."
)

_SUMMARIZE_CONTRACT = """[TASK — summarize the conversation so far]

Produce a concise, board-ready recap of the discussion using ONLY what the
transcript contains. Use these `### ` H3 sections, and OMIT any section the
transcript has nothing for (never pad):

### Objective
What the user set out to understand.

### Key findings
The concrete, quantified results reached (bold the critical numbers).

### Decisions
Any choices that were settled.

### Recommendations
Actions the analyst proposed.

### Open questions
What is still unresolved or unanswered.

Keep it tight. Do NOT invent numbers, findings, or recommendations that are not
in the transcript. Do NOT re-run or re-derive analysis."""

_RECALL_CONTRACT = """[TASK — answer a question about what was already said]

The user is asking you to recall something from earlier in THIS conversation
(e.g. what you recommended, concluded, or decided). Answer their question
directly and specifically using ONLY the transcript: quote the relevant
findings/recommendations and the context they applied to. If the transcript
does not contain it, say so plainly rather than inventing an answer. Do NOT
re-run analysis."""


def _format_transcript(chat_history: dict[str, Any] | None) -> str:
    """Render the stored chat history into a compact two-sided transcript.

    Keeps only the spoken turns (user questions + analyst answers); chart/SQL/
    clarify entries are noted as markers, not dumped. Trims to the most recent
    messages and a character budget so the meta call stays cheap.
    """
    if not chat_history:
        return ""
    messages = chat_history.get("messages") or []
    lines: List[str] = []
    for msg in messages[-_MAX_TRANSCRIPT_MESSAGES:]:
        if not isinstance(msg, dict):
            continue
        kind = msg.get("type")
        content = (msg.get("content") or "").strip()
        if kind == "HumanMessage" and content:
            lines.append(f"User: {content}")
        elif kind == "AIMessage" and content:
            lines.append(f"Analyst: {content}")
        elif kind in ("SQLOutputForCharts",):
            lines.append("Analyst: [chart]")
        elif kind == "DataOverflow" and content:
            lines.append(f"Analyst: {content}")
    transcript = "\n".join(lines).strip()
    if len(transcript) > _MAX_TRANSCRIPT_CHARS:
        # Keep the tail — the most recent turns hold the current conclusions.
        transcript = "…\n" + transcript[-_MAX_TRANSCRIPT_CHARS:]
    return transcript


def _load_transcript(state: AgentState) -> str:
    """Pull the full saved transcript for this thread, or '' when unavailable."""
    user_id = state.get("user_id")
    thread_id = state.get("thread_id")
    if not user_id or not thread_id:
        return ""
    try:
        chat_history = load_conversation(user_id, thread_id)
    except Exception as exc:  # noqa: BLE001 - a recap must never crash the turn
        log_event(
            logger,
            "conversation_transcript_load_error",
            logging.ERROR,
            node="conversation_node",
            error=str(exc),
        )
        return ""
    return _format_transcript(chat_history)


def conversation_node(state: AgentState) -> AgentState:
    """Answer a conversation meta-request from the transcript (no new SQL).

    Writes to `out_of_scope_answer` + sets `current_route='fallback'` so the UI's
    existing prose renderer shows it, and clears `followup_questions` so a recap
    isn't trailed by stale or generic suggestion chips.
    """
    rc = state.get("routing_context")
    intent = conversation_intent_of(rc)
    question = state["messages"][-1].content if state.get("messages") else ""
    transcript = _load_transcript(state)

    if not transcript:
        log_event(
            logger,
            "conversation_meta_empty_transcript",
            node="conversation_node",
            intent=intent,
        )
        return {
            "out_of_scope_answer": _EMPTY_TRANSCRIPT,
            "current_route": "fallback",
            "followup_questions": [],
        }

    contract = _SUMMARIZE_CONTRACT if intent == "summarize_chat" else _RECALL_CONTRACT
    system_prompt = (
        "You are an insurance analyst reflecting on your own conversation with a "
        "leader. You restate and organize what was already discussed; you do not "
        "perform new analysis.\n\n" + contract
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=(
                f"[CONVERSATION TRANSCRIPT]\n{transcript}\n\n"
                f"[USER REQUEST]\n{question}"
            )
        ),
    ]
    try:
        response = Initialization.llm_creative.invoke(messages)
        answer = (getattr(response, "content", "") or "").strip()
    except Exception as exc:  # noqa: BLE001 - best-effort; degrade gracefully
        log_event(
            logger,
            "conversation_meta_error",
            logging.ERROR,
            node="conversation_node",
            intent=intent,
            error=str(exc),
        )
        answer = ""

    if not answer:
        answer = (
            "I couldn't put together a recap of the conversation just now. "
            "Please try again."
        )

    log_event(
        logger,
        "conversation_meta_answered",
        node="conversation_node",
        intent=intent,
        transcript_chars=len(transcript),
    )
    return {
        "out_of_scope_answer": answer,
        "current_route": "fallback",
        "followup_questions": [],
    }
