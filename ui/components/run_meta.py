"""The answer's meter: how long it took and what it cost, one quiet chip.

Closed, it is one line in the answer footer — "8.4s · 12.3k tokens". Open, it is
the turn's timeline (which step took the time) and its model usage (calls, input
and output tokens, the models used). A native ``<details>``, so opening it costs
no callback.

Pure presentation: the trace dict in (:func:`core.run_trace.build_trace`),
components out. An answer saved before the meter existed has no trace and shows
no chip rather than a zero.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from dash import html

from core.run_trace import format_duration, format_tokens


def _summary_bits(run: Dict[str, Any]) -> List[Any]:
    tokens = int(((run.get("tokens") or {}).get("total_tokens")) or 0)
    bits: List[Any] = [
        html.I(className="bi bi-lightning-charge-fill run-meta-icon"),
        html.Span(format_duration(run.get("elapsed_ms")), className="run-meta-time"),
    ]
    if tokens:
        bits += [html.Span("·", className="run-meta-sep"),
                 html.Span(f"{format_tokens(tokens)} tokens", className="run-meta-tokens")]
    return bits


def _timeline(run: Dict[str, Any]) -> Optional[Any]:
    steps = [s for s in run.get("steps") or [] if s.get("duration_ms") is not None]
    if not steps:
        return None
    longest = max((int(s.get("duration_ms") or 0) for s in steps), default=0) or 1
    rows = []
    for step in steps:
        duration = int(step.get("duration_ms") or 0)
        rows.append(html.Div(
            [
                html.Span(step.get("label") or step.get("node"), className="run-step-label"),
                html.Span(
                    html.Span(className="run-step-fill",
                              style={"width": f"{max(4, round(duration / longest * 100))}%"}),
                    className="run-step-track",
                ),
                html.Span(format_duration(duration), className="run-step-time"),
            ],
            className="run-step",
        ))
    return html.Div([html.Div("Where the time went", className="run-meta-heading"), *rows],
                    className="run-meta-section")


def _usage(run: Dict[str, Any]) -> Optional[Any]:
    calls = int(run.get("llm_calls") or 0)
    if not calls:
        return None
    tokens = run.get("tokens") or {}
    cells = [
        ("Model calls", str(calls)),
        ("Input", format_tokens(tokens.get("input_tokens"))),
        ("Output", format_tokens(tokens.get("output_tokens"))),
        ("Total", format_tokens(tokens.get("total_tokens"))),
    ]
    if tokens.get("cached_tokens"):
        cells.append(("Cached", format_tokens(tokens.get("cached_tokens"))))
    models = ", ".join(run.get("models") or [])
    return html.Div(
        [
            html.Div("Model usage", className="run-meta-heading"),
            html.Div([
                html.Div([html.Div(value, className="run-cell-value"),
                          html.Div(label, className="run-cell-label")], className="run-cell")
                for label, value in cells
            ], className="run-cells"),
            html.Div(models, className="run-meta-models") if models else None,
        ],
        className="run-meta-section",
    )


def conversation_usage(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    """Totals over every answer in a transcript that carries a trace. Pure."""
    totals = {"answers": 0, "total_tokens": 0, "elapsed_ms": 0, "llm_calls": 0}
    for message in messages or []:
        run = message.get("run") if isinstance(message, dict) else None
        if not isinstance(run, dict):
            continue
        totals["answers"] += 1
        totals["total_tokens"] += int((run.get("tokens") or {}).get("total_tokens") or 0)
        totals["elapsed_ms"] += int(run.get("elapsed_ms") or 0)
        totals["llm_calls"] += int(run.get("llm_calls") or 0)
    return totals


def _conversation(totals: Optional[Dict[str, int]]) -> Optional[Any]:
    if not totals or totals.get("answers", 0) < 2:
        return None
    return html.Div(
        [
            html.Div("This conversation", className="run-meta-heading"),
            html.Div(
                f"{totals['answers']} answers · {format_tokens(totals['total_tokens'])} tokens · "
                f"{totals['llm_calls']} model calls · {format_duration(totals['elapsed_ms'])} of analysis",
                className="run-meta-conversation",
            ),
        ],
        className="run-meta-section",
    )


def run_meta(run: Optional[Dict[str, Any]], totals: Optional[Dict[str, int]] = None):
    """The chip for one answer, or None when the answer carries no trace."""
    if not isinstance(run, dict) or not run.get("elapsed_ms"):
        return None
    body = [part for part in (_timeline(run), _usage(run), _conversation(totals))
            if part is not None]
    return html.Details(
        [
            html.Summary(_summary_bits(run), className="run-meta-summary",
                         title="Time and tokens used for this answer"),
            html.Div(body or [html.Div("No model calls were needed for this answer.",
                                       className="run-meta-empty")],
                     className="run-meta-panel"),
        ],
        className="run-meta",
    )
