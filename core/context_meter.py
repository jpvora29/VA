"""What a model call's prompt is made of, and how full its context window is.

The run meter (:mod:`core.run_trace`) counts tokens per call; this module says
what those tokens WERE: instructions, rules, tool definitions, schema, earlier
results, data, the solver's own working, the question. It powers the context
chip in the answer footer, the way Claude Code's context view splits a window.

Two facts make it cheap and honest:

* Every prompt in the app labels its blocks with bracketed headers — the solver
  writes ``[DOMAIN RULES …]`` and ``[SUB-QUESTION …]``, and the signature layer
  renders each input as ``[FIELD_NAME]`` (:mod:`core.llm.prompt`). Splitting on
  those headers attributes text to a category without knowing which node wrote
  the prompt.
* Characters are measured, then SCALED to the provider's reported input token
  count, so the categories always sum to the real number. Characters only decide
  the proportions; no tokenizer is needed.

Pure functions, no LangChain import: messages are read by duck typing.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

#: (key, label) in display order. The order is also the stacked bar's colour
#: order, so a category keeps its colour on every answer.
CATEGORIES: Tuple[Tuple[str, str], ...] = (
    ("instructions", "Instructions"),
    ("rules", "Rules & skills"),
    ("tools", "Tool definitions"),
    ("schema", "Schema & values"),
    ("history", "Earlier results & history"),
    ("data", "Data & evidence"),
    ("working", "Tool calls & results"),
    ("question", "Question & inputs"),
)
CATEGORY_LABELS: Dict[str, str] = dict(CATEGORIES)

#: Header keywords -> category, tried in order (the first hit wins), so the
#: order is load-bearing: "RESULTS FROM EARLIER STEPS" must reach `history`
#: before "RESULT" reaches `data`.
_HEADER_CATEGORIES: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("YOUR ROLE", "CONFIDENTIALITY", "INSTRUCTIONS"), "instructions"),
    (("EARLIER", "PRIOR", "HISTORY", "CONVERSATION", "PREVIOUS"), "history"),
    (("SCHEMA", "PRIMARY FLOW", "VALID_VALUES", "VALID VALUES", "VALID_YEAR",
      "DEFINITIONS", "COLUMNS", "CANDIDATES"), "schema"),
    (("RULES", "CALCULATIONS", "LENS", "SKILL", "EXAMPLE", "FEW_SHOT",
      "PRINCIPLES"), "rules"),
    # Before `question`: "QUERY_PLAN" is a plan, not the user's query.
    (("QUERY_PLAN",), "data"),
    # Before `data`: "[SUB-QUESTION — answer only this]" mentions an answer.
    (("QUESTION", "QUERY", "REQUEST"), "question"),
    (("_OUTPUT", "EVIDENCE", "ROWS", "RESULT", "FACTS", "CLAIMS", "DATA",
      "COMMENTARY", "ANSWER", "REASONING"), "data"),
)

#: A block header: a line opening with "[" and an upper-case run. Only the
#: upper-case lead-in is captured, because real headers run long and wrap —
#: "[LENS TO APPLY — follow this shape …" closes its bracket two lines later.
_HEADER = re.compile(r"^\[([A-Z][A-Z0-9_ /\-—]*)", re.MULTILINE)

#: Message type -> the category of text not under any recognised header.
_DEFAULT_FOR_TYPE = {
    "system": "instructions",
    "human": "question",
    "user": "question",
    "ai": "working",
    "assistant": "working",
    "tool": "working",
    "function": "working",
}

#: Context window by model-name fragment, most specific first. Deployment
#: names vary ("gpt-41-mini", "gpt-4.1-mini"), so both spellings are listed.
_WINDOWS: Tuple[Tuple[str, int], ...] = (
    ("gpt-4.1", 1_047_576),
    ("gpt-41", 1_047_576),
    ("gpt-5", 400_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("o4-mini", 200_000),
    ("o3", 200_000),
    ("o1", 200_000),
    ("gpt-35", 16_385),
    ("gpt-3.5", 16_385),
)
DEFAULT_WINDOW = 128_000

_CHARS_PER_TOKEN = 4


def context_window(model: str) -> int:
    """The model's context window in tokens; 128k when the name is unknown."""
    name = (model or "").lower()
    for fragment, window in _WINDOWS:
        if fragment in name:
            return window
    return DEFAULT_WINDOW


def category_for_header(header: str) -> str:
    """The category a ``[HEADER]`` block belongs to, or "" when none fits."""
    upper = header.upper()
    for keywords, category in _HEADER_CATEGORIES:
        if any(keyword in upper for keyword in keywords):
            return category
    return ""


def split_text(text: str, default: str, *, nested: bool = False) -> Dict[str, int]:
    """Characters per category for one message, split at its block headers.

    An unrecognised header starts a `default` block — unless `nested`, where it
    stays in the enclosing block. A system prompt nests: a skill body inside
    the rules carries its own "[GPR SQL GENERATION]" heading, and that text is
    still rules. A signature's user prompt does not: every "[FIELD]" there is a
    top-level input.
    """
    counts: Counter = Counter()
    position, current = 0, default
    for match in _HEADER.finditer(text or ""):
        counts[current] += match.start() - position
        current = category_for_header(match.group(1)) or (current if nested else default)
        position = match.start()
    counts[current] += len(text or "") - position
    return {key: value for key, value in counts.items() if value > 0}


def _content_text(content: Any) -> str:
    """A message's text, whether a plain string or a list of content parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, Mapping):
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return str(content or "")


def measure_message(message: Any) -> Dict[str, int]:
    """Characters per category for one chat message (duck-typed)."""
    kind = str(getattr(message, "type", "") or "human").lower()
    default = _DEFAULT_FOR_TYPE.get(kind, "question")
    text = _content_text(getattr(message, "content", ""))
    if default == "working":
        counts = {"working": len(text)}
    else:
        counts = split_text(text, default, nested=(default == "instructions"))
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        counts["working"] = counts.get("working", 0) + len(json.dumps(tool_calls, default=str))
    return counts


def measure_prompt(messages: Iterable[Any], tools: Any = None) -> Dict[str, int]:
    """Characters per category for a whole prompt: its messages plus tool schemas."""
    total: Counter = Counter()
    for message in messages or []:
        total.update(measure_message(message))
    if tools:
        total["tools"] += len(json.dumps(tools, default=str))
    return {key: value for key, value in total.items() if value > 0}


def scale_to_tokens(chars: Mapping[str, int], input_tokens: int) -> Dict[str, int]:
    """Spread the reported input tokens over the categories by their share.

    Largest-remainder rounding, so the parts sum exactly to `input_tokens`. With
    no reported count (a provider that returns no usage) it falls back to an
    estimate of four characters per token.
    """
    total_chars = sum(chars.values())
    if total_chars <= 0:
        return {}
    if input_tokens <= 0:
        return {key: max(1, value // _CHARS_PER_TOKEN) for key, value in chars.items()}
    exact = {key: value * input_tokens / total_chars for key, value in chars.items()}
    floors = {key: int(value) for key, value in exact.items()}
    short = input_tokens - sum(floors.values())
    by_remainder = sorted(exact, key=lambda key: exact[key] - floors[key], reverse=True)
    for key in by_remainder[:short]:
        floors[key] += 1
    return {key: value for key, value in floors.items() if value > 0}


def ordered_split(split: Mapping[str, int]) -> List[Dict[str, Any]]:
    """A split as JSON-safe rows in display order, empty categories dropped."""
    return [{"key": key, "tokens": int(split[key])}
            for key, _label in CATEGORIES if split.get(key)]


def _used(call: Any) -> int:
    """Input tokens one call sent: the reported count, else the measured split."""
    return int(call.input_tokens or sum(call.context.values()))


def _fill_of(call: Any) -> float:
    return _used(call) / context_window(call.model)


def context_summary(calls: Sequence[Any]) -> Dict[str, Any]:
    """The context view for one turn: its fullest prompt, and all input split.

    `calls` are :class:`core.run_trace.ModelCall` objects carrying a `context`
    split. The PEAK is the single prompt that came closest to its model's window,
    which is what "how full is the context" means when a turn makes many calls.
    Returns {} when no call was measured.
    """
    measured = [call for call in calls if getattr(call, "context", None)]
    if not measured:
        return {}
    peak = max(measured, key=_fill_of)
    turn: Counter = Counter()
    for call in measured:
        turn.update(call.context)
    return {
        "peak": {
            "node": peak.node,
            "model": peak.model,
            "used": _used(peak),
            "window": context_window(peak.model),
            "split": ordered_split(peak.context),
        },
        "turn": {
            "calls": len(measured),
            "input_tokens": sum(_used(call) for call in measured),
            "cached_tokens": sum(int(call.cached_tokens or 0) for call in measured),
            "split": ordered_split(turn),
        },
    }
