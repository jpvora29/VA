"""The answer's context chip: how full the context window got, and with what.

Closed, it is a small ring and a percentage in the answer footer — the share of
the model's context window taken by this turn's FULLEST prompt. Hovered or
focused, it splits that prompt by what it was made of (instructions, rules, tool
definitions, schema, earlier results, data, tool calls, the question) beside the
free space left, and then splits everything the turn sent across all its model
calls — which is where a large token total actually comes from.

Pure presentation: the `context` block of a trace in
(:func:`core.context_meter.context_summary`), components out. Opening it costs no
callback; the panel is CSS-revealed. An answer without a measured context shows
no chip.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from dash import html

from core.context_meter import CATEGORIES
from core.run_trace import format_tokens

#: Graph node -> how a reader would name the step that sent the prompt.
_NODE_LABELS = {
    "model": "Analysis step",
    "writer_node": "Answer writer",
    "context_filler": "Reading the question",
    "intent_classifier": "Classifying the question",
    "clarify_decide": "Checking for ambiguity",
    "rephraser_agent": "Rephrasing the question",
    "followup_node": "Follow-up suggestions",
    "planner_node": "Planning the analysis",
    "schema_identifier_node": "Finding the columns",
}

#: At or above this fill the ring turns amber and the label says so.
_NEAR_LIMIT = 0.8


def node_label(node: str) -> str:
    """A step name a reader recognises; unknown nodes are de-snaked."""
    if node in _NODE_LABELS:
        return _NODE_LABELS[node]
    words = (node or "model call").removesuffix("_node").replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def format_share(part: float, whole: float) -> str:
    """0.0141 -> "1.4%"; one decimal under 10%, whole numbers above."""
    if whole <= 0:
        return "0%"
    share = part / whole * 100
    if 0 < share < 0.1:
        return "<0.1%"
    return f"{share:.1f}%" if share < 10 else f"{share:.0f}%"


def _bar(split: List[Dict[str, Any]], whole: int) -> Any:
    """A stacked bar: one segment per category, widths as shares of `whole`."""
    return html.Div(
        [
            html.Span(
                className=f"ctx-seg ctx-k-{row['key']}",
                style={"width": f"{row['tokens'] / whole * 100:.3f}%"},
            )
            for row in split
        ],
        className="ctx-bar",
    )


def _caption(label: str, detail: str) -> Any:
    return html.Div([html.Span(label, className="ctx-caption-label"),
                     html.Span(detail, className="ctx-caption-detail")],
                    className="ctx-caption")


def _cell(tokens: Optional[int], share: str = "") -> Any:
    """One figure in the table: tokens, then their share in muted ink."""
    if tokens is None:
        return html.Span("—", className="ctx-cell is-empty")
    parts = [html.Span(format_tokens(tokens), className="ctx-cell-tokens")]
    if share:
        parts.append(html.Span(share, className="ctx-cell-share"))
    return html.Span(parts, className="ctx-cell")


def _table_row(key: str, label: str, peak_cell: Any, turn_cell: Any) -> Any:
    return html.Div(
        [html.Span(className=f"ctx-dot ctx-k-{key}"),
         html.Span(label, className="ctx-row-label"), peak_cell, turn_cell],
        className="ctx-row",
    )


def _breakdown(peak: Dict[str, Any], turn: Dict[str, Any]) -> Any:
    """One table, one row per category: the fullest prompt beside the whole turn.

    Side by side because they answer different questions — the first is how
    close a single call came to its window, the second is where the turn's
    token total came from — and the reader is usually comparing the two.
    """
    used, window = int(peak["used"]), int(peak["window"])
    turn_total = int(turn.get("input_tokens") or 0)
    in_peak = {row["key"]: row["tokens"] for row in peak.get("split") or []}
    in_turn = {row["key"]: row["tokens"] for row in turn.get("split") or []}
    rows = [
        _table_row(key, label,
                   _cell(in_peak.get(key), format_share(in_peak.get(key, 0), used))
                   if key in in_peak else _cell(None),
                   _cell(in_turn.get(key), format_share(in_turn.get(key, 0), turn_total))
                   if key in in_turn else _cell(None))
        for key, label in CATEGORIES
        if key in in_peak or key in in_turn
    ]
    rows.append(_table_row("free", "Free space", _cell(max(0, window - used)), _cell(None)))
    head = html.Div([html.Span(), html.Span(),
                     html.Span("Fullest prompt", className="ctx-col-head"),
                     html.Span("Whole turn", className="ctx-col-head")],
                    className="ctx-row ctx-row-head")
    return html.Div([head, *rows], className="ctx-rows")


def _panel(peak: Dict[str, Any], turn: Dict[str, Any]) -> List[Any]:
    used, window = int(peak["used"]), int(peak["window"])
    source = node_label(peak.get("node") or "")
    if peak.get("model"):
        source = f"{source} · {peak['model']}"
    turn_total = int(turn.get("input_tokens") or 0)
    calls = int(turn.get("calls") or 0)
    cached = int(turn.get("cached_tokens") or 0)
    turn_detail = f"{format_tokens(turn_total)} over {calls} model call{'s' if calls != 1 else ''}"
    if cached:
        turn_detail += f" · {format_share(cached, turn_total)} served from cache"
    parts: List[Any] = [
        html.Div("Context window", className="run-meta-heading"),
        html.Div(
            [html.Strong(f"{format_tokens(used)} / {format_tokens(window)}"),
             html.Span(f" tokens · {format_share(used, window)} full")],
            className="ctx-headline",
        ),
        html.Div(f"Fullest prompt this turn: {source}", className="ctx-source"),
        _caption("Fullest prompt", format_tokens(used)),
        _bar(peak.get("split") or [], used),
    ]
    if turn_total and turn.get("split"):
        parts += [_caption("Whole turn", turn_detail), _bar(turn["split"], turn_total)]
    parts.append(_breakdown(peak, turn))
    return parts


def context_meter(run: Optional[Dict[str, Any]]):
    """The chip for one answer, or None when its context was not measured."""
    context = (run or {}).get("context") if isinstance(run, dict) else None
    peak = (context or {}).get("peak")
    if not peak or not peak.get("window"):
        return None
    used, window = int(peak.get("used") or 0), int(peak["window"])
    fill = used / window
    near_limit = fill >= _NEAR_LIMIT
    label = f"{format_share(used, window)} context" + (" · near limit" if near_limit else "")
    return html.Div(
        [
            html.Span(
                [
                    html.Span(
                        className="ctx-ring" + (" is-near-limit" if near_limit else ""),
                        # At least a visible sliver: an empty ring reads as "not measured".
                        style={"--ctx-fill": f"{max(fill, 0.02) * 360:.1f}deg"},
                    ),
                    html.Span(label, className="ctx-meter-label"),
                ],
                className="ctx-meter-chip",
                tabIndex=0,
                **{"aria-label": f"Context window {format_share(used, window)} full. "
                                 "Hover or focus for the breakdown."},
            ),
            html.Div(_panel(peak, context.get("turn") or {}),
                     className="ctx-meter-panel", role="tooltip"),
        ],
        className="ctx-meter",
    )
