"""Recap workspace — the shell is real, the engine is not built yet."""
from __future__ import annotations

from dash import html

from ui.shell.placeholder import placeholder_body, placeholder_rail

STEPS = ("Choose period", "Pick sources", "Draft recap", "Review & send")


def recap_rail() -> html.Aside:
    return placeholder_rail("recap", "Recap", STEPS)


def recap_body() -> html.Div:
    return placeholder_body(
        icon="bi-journal-text",
        title="Period recap",
        blurb=(
            "A written recap of what changed over a period — built from the same "
            "evidence pack the Studio deck and the analyst's answers already use, so "
            "the numbers agree wherever they appear."
        ),
        bullets=(
            "Pick a carrier, market and window; the recap scopes itself to that.",
            "Every figure traces back to a fact id, exactly as in Studio commentary.",
            "Export to a document, or hand the draft to the Chatbot to interrogate.",
        ),
    )
