"""Keeps the composer's context ring in step with the open conversation.

One callback: the transcript changes (a turn lands, a chat is opened, New chat
empties it) and the ring is redrawn from the newest answer's measured context.
"""
from dash import Input, Output, callback

from ui.components.context_meter import context_indicator


@callback(
    Output("context-indicator", "children"),
    Input("chat-store", "data"),
)
def refresh_context_indicator(chat_history):
    """The ring for the open chat, redrawn from its transcript."""
    return context_indicator((chat_history or {}).get("messages") or [])
