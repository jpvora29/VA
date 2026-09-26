"""Usage & speed — the observability ledger, as a page a person can read.

Reads the persisted turn traces (:mod:`core.store.run_traces`): how long the
user's answers take (median and slow tail), what they cost in tokens and model
calls, and the last few turns with their numbers. Pure presentation — dicts in,
components out; the callback in `ui.callbacks` loads the rows.
"""
from __future__ import annotations

from typing import Any, Dict, List

import dash_bootstrap_components as dbc
from dash import html

from core.run_trace import format_duration, format_tokens


def _tile(value: str, label: str, hint: str = ""):
    return html.Div(
        [html.Div(value, className="usage-tile-value"),
         html.Div(label, className="usage-tile-label"),
         html.Div(hint, className="usage-tile-hint") if hint else None],
        className="usage-tile",
    )


def _row(trace: Dict[str, Any]):
    status = str(trace.get("status") or "ok")
    return html.Tr([
        html.Td(str(trace.get("question") or "—")[:90], className="usage-q"),
        html.Td(format_duration(trace.get("elapsed_ms")), className="num"),
        html.Td(format_tokens(trace.get("total_tokens")), className="num"),
        html.Td(str(trace.get("llm_calls") or 0), className="num"),
        html.Td(html.Span(status, className=f"usage-status is-{status}")),
    ])


def usage_body(summary: Dict[str, Any], recent: List[Dict[str, Any]]):
    """The modal's content for one user."""
    if not summary or not summary.get("turns"):
        return html.Div(
            [html.I(className="bi bi-speedometer2 usage-empty-icon"),
             html.Div("No answers measured yet", className="usage-empty-title"),
             html.Div("Every answer you ask for from now on is timed and metered here.",
                      className="usage-empty-sub")],
            className="usage-empty",
        )
    tiles = html.Div(
        [
            _tile(format_duration(summary.get("p50_ms")), "Typical answer", "median time"),
            _tile(format_duration(summary.get("p95_ms")), "Slowest 5%", "p95 time"),
            _tile(format_tokens(summary.get("avg_tokens")), "Tokens per answer", "average"),
            _tile(str(summary.get("turns")), "Answers measured",
                  f"{format_tokens(summary.get('total_tokens'))} tokens in total"),
        ],
        className="usage-tiles",
    )
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Question"), html.Th("Time", className="num"),
                             html.Th("Tokens", className="num"),
                             html.Th("Model calls", className="num"), html.Th("")])),
         html.Tbody([_row(t) for t in recent[:10]])],
        className="usage-table",
    )
    return html.Div([tiles, html.Div("Latest answers", className="usage-section"), table])


def usage_modal():
    """Mounted once with the chat page; filled when opened from Tools."""
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle([html.I(className="bi bi-speedometer2 me-2"),
                                            "Usage & speed"])),
            dbc.ModalBody(id="usage-body"),
        ],
        id="usage-modal",
        is_open=False,
        size="lg",
        centered=True,
        className="usage-modal",
    )
