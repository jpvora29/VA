"""The conversation's context indicator: one small ring beside the send button.

Like Claude Code's context gauge, it fills — and changes colour — as the
conversation's context fills. The ring shows the context the assistant held on
its LATEST answer: that answer's largest prompt, against the model's context
window. Hovered or focused, it splits that context by what filled it
(instructions, rules, tool definitions, schema, earlier results, data, tool
calls, the question) beside the free space left.

Pure presentation: the transcript's messages in, components out. Each answer's
trace carries its measured context (:func:`core.context_meter.context_summary`);
a chat with no measured answer yet shows an empty ring.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from dash import html

from core.context_meter import CATEGORIES
from core.run_trace import format_tokens

#: Fill at which the ring turns amber, then red (Claude Code's warning bands).
_WARN_AT = 0.5
_FULL_AT = 0.8


def latest_context(messages: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The newest answer's measured context ({"used", "window", "split"}), or {}."""
    for message in reversed(list(messages or [])):
        run = message.get("run") if isinstance(message, dict) else None
        peak = ((run or {}).get("context") or {}).get("peak") if isinstance(run, dict) else None
        if peak and peak.get("window"):
            return peak
    return {}


def chat_input_tokens(messages: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Input tokens sent over the whole chat, and how many answers sent them."""
    answers = tokens = 0
    for message in messages or []:
        run = message.get("run") if isinstance(message, dict) else None
        turn = (((run or {}).get("context") or {}).get("turn") or {}) if isinstance(run, dict) else {}
        if turn.get("input_tokens"):
            answers += 1
            tokens += int(turn["input_tokens"])
    return {"answers": answers, "tokens": tokens}


def format_share(part: float, whole: float) -> str:
    """0.0141 -> "1.4%"; one decimal under 10%, whole numbers above."""
    if whole <= 0:
        return "0%"
    share = part / whole * 100
    if 0 < share < 0.1:
        return "<0.1%"
    return f"{share:.1f}%" if share < 10 else f"{share:.0f}%"


def fill_level(fill: float) -> str:
    """The ring's colour band: "low", "warn" (from 50%) or "full" (from 80%)."""
    if fill >= _FULL_AT:
        return "full"
    if fill >= _WARN_AT:
        return "warn"
    return "low"


def _bar(split: List[Dict[str, Any]], window: int) -> Any:
    """The window as one bar: each category's share, then the free space."""
    used = sum(int(row["tokens"]) for row in split)
    segments = [
        html.Span(className=f"ctx-seg ctx-k-{row['key']}",
                  style={"width": f"{row['tokens'] / window * 100:.3f}%"})
        for row in split
    ]
    segments.append(html.Span(className="ctx-seg ctx-k-free",
                              style={"width": f"{max(0, window - used) / window * 100:.3f}%"}))
    return html.Div(segments, className="ctx-bar")


def _row(key: str, label: str, tokens: int, window: int) -> Any:
    return html.Div(
        [
            html.Span(className=f"ctx-dot ctx-k-{key}"),
            html.Span(label, className="ctx-row-label"),
            html.Span(format_tokens(tokens), className="ctx-row-tokens"),
            html.Span(format_share(tokens, window), className="ctx-row-share"),
        ],
        className="ctx-row",
    )


def _panel(peak: Dict[str, Any], totals: Dict[str, int]) -> List[Any]:
    used, window = int(peak.get("used") or 0), int(peak["window"])
    split = peak.get("split") or []
    labels = dict(CATEGORIES)
    rows = [_row(row["key"], labels.get(row["key"], row["key"]), int(row["tokens"]), window)
            for row in split]
    rows.append(_row("free", "Free space", max(0, window - used), window))
    parts: List[Any] = [
        html.Div("Context window", className="ctx-heading"),
        html.Div(
            [html.Strong(f"{format_tokens(used)} / {format_tokens(window)}"),
             html.Span(f" tokens · {format_share(used, window)} used")],
            className="ctx-headline",
        ),
        html.Div(f"{peak.get('model') or 'Model'} · as of the last answer", className="ctx-source"),
        _bar(split, window),
        html.Div(rows, className="ctx-rows"),
    ]
    if totals.get("answers"):
        count = totals["answers"]
        parts.append(html.Div(
            f"This chat so far: {format_tokens(totals['tokens'])} tokens sent over "
            f"{count} answer{'s' if count != 1 else ''}",
            className="ctx-footnote",
        ))
    return parts


def _empty_panel() -> List[Any]:
    return [
        html.Div("Context window", className="ctx-heading"),
        html.Div("Nothing used yet. This fills as the conversation runs.",
                 className="ctx-source"),
    ]


def context_indicator(messages: Sequence[Dict[str, Any]]) -> List[Any]:
    """The ring and its hover panel, for the open conversation's transcript."""
    peak = latest_context(messages)
    window = int(peak.get("window") or 0)
    used = int(peak.get("used") or 0)
    fill = used / window if window else 0.0
    level = fill_level(fill) if window else "empty"
    label = (f"Context {format_share(used, window)} used" if window
             else "Context: nothing used yet")
    return [
        html.Span(
            html.Span(
                className=f"ctx-ring is-{level}",
                # Never a bare 0°: a hairline says "measured, and nearly empty".
                style={"--ctx-fill": f"{max(fill, 0.015) * 360:.1f}deg" if window else "0deg"},
            ),
            className="ctx-indicator-btn",
            tabIndex=0,
            role="button",
            **{"aria-label": f"{label}. Hover or focus for the breakdown."},
        ),
        html.Div(_panel(peak, chat_input_tokens(messages)) if window else _empty_panel(),
                 className="ctx-panel", role="tooltip"),
    ]
