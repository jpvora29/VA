"""Minutes-of-meeting workspace — the shell is real, the engine is not built yet."""
from __future__ import annotations

from dash import html

from ui.shell.placeholder import placeholder_body, placeholder_rail

STEPS = ("Add transcript", "Extract decisions", "Draft minutes", "Circulate")


def mom_rail() -> html.Aside:
    return placeholder_rail("mom", "MoM", STEPS)


def mom_body() -> html.Div:
    return placeholder_body(
        icon="bi-card-checklist",
        title="Minutes of meeting",
        blurb=(
            "Turn a meeting transcript into circulated minutes: attendees, decisions, "
            "owners and dates — with each decision landing on the same Decision Board "
            "the Chatbot already writes to."
        ),
        bullets=(
            "Upload or paste a transcript; attendees and agenda are read from it.",
            "Decisions and actions are extracted with an owner and a due date.",
            "Confirmed decisions are pinned to the Decision Board, not a second list.",
        ),
    )
