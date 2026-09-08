"""The guided tour — what this application is, in eight screens.

New users arrive at a prompt box and guess what it can do, and most guess low:
they type a lookup, get a number, and never find out about the evidence panel,
the drivers decomposition, Boardroom Mode or Studio. A tour is the cheapest fix
for that, and it only works if it SHOWS rather than tells — so every step carries
a drawn illustration of the thing it is describing, not a paragraph about it.

The illustrations are inline SVG, drawn from the app's own design tokens. That is
deliberate: a screenshot goes stale the first time a button moves, has to be
re-shot per theme, and adds binary files to the repo. A drawn panel stays true to
the shape of the UI (a composer with a send button, a card with a chart in it)
without pretending to be a pixel-accurate photograph of it.

Steps are data. Adding one is adding a `TourStep` to `STEPS`; the dots, the
counter and the navigation all read from that list.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Tuple

from dash import html

# The tour's palette, taken from the shared tokens so an illustration cannot
# drift from the interface it is drawing.
_INK = "var(--va-ink-700, #2c3550)"
_MUTED = "var(--va-ink-300, #98a2b8)"
_LINE = "var(--va-border-mid, #d7dced)"
_SURFACE = "var(--va-surface-1, #f5f7fb)"
_BLUE = "var(--va-blue, #0b4bff)"
_SOFT = "var(--va-blue-soft, #eef3ff)"
_GOOD = "var(--va-good, #1f9d55)"
_WARN = "var(--va-warn, #b9810a)"


def _svg(*children, view: str = "0 0 320 180"):
    return html.Div(
        html.Div(
            children,
            className="tour-canvas",
            **{"data-view": view},
        ),
        className="tour-art",
    )


def _box(x, y, w, h, *, fill=_SURFACE, stroke=_LINE, radius=8, cls=""):
    return html.Div(
        className=f"tour-shape {cls}".strip(),
        style={
            "left": f"{x}px", "top": f"{y}px", "width": f"{w}px", "height": f"{h}px",
            "background": fill, "border": f"1px solid {stroke}",
            "borderRadius": f"{radius}px",
        },
    )


def _text(x, y, w, text, *, size=9, weight=600, color=_INK, cls=""):
    return html.Div(
        text,
        className=f"tour-label {cls}".strip(),
        style={
            "left": f"{x}px", "top": f"{y}px", "width": f"{w}px",
            "fontSize": f"{size}px", "fontWeight": weight, "color": color,
        },
    )


def _bar(x, y, w, h, *, fill=_BLUE, radius=3):
    return html.Div(
        className="tour-shape",
        style={
            "left": f"{x}px", "top": f"{y}px", "width": f"{w}px", "height": f"{h}px",
            "background": fill, "borderRadius": f"{radius}px", "border": "none",
        },
    )


# ── the illustrations ────────────────────────────────────────────────────────


def art_ask():
    """The composer: type a question the way you would say it."""
    return _svg(
        _box(20, 30, 280, 62, fill="#ffffff"),
        _text(34, 44, 200, "Which product lines is Zurich"),
        _text(34, 58, 200, "growing fastest in Canada?"),
        _box(258, 46, 28, 28, fill=_BLUE, stroke=_BLUE, radius=14),
        _text(258, 54, 28, "↑", size=13, weight=800, color="#ffffff", cls="tour-center"),
        _box(20, 104, 90, 22, fill=_SOFT, stroke=_SOFT, radius=11),
        _text(20, 110, 90, "/brief", size=9, weight=700, color=_BLUE, cls="tour-center"),
        _box(118, 104, 90, 22, fill=_SOFT, stroke=_SOFT, radius=11),
        _text(118, 110, 90, "/compare", size=9, weight=700, color=_BLUE, cls="tour-center"),
        _box(216, 104, 84, 22, fill=_SOFT, stroke=_SOFT, radius=11),
        _text(216, 110, 84, "/explain", size=9, weight=700, color=_BLUE, cls="tour-center"),
        _text(20, 138, 280, "Type “/” to see every task it can do.", size=9, color=_MUTED),
    )


def art_answer():
    """One card: the finding, its scope, and the evidence under it."""
    return _svg(
        _box(20, 18, 280, 144, fill="#ffffff"),
        _box(32, 28, 52, 14, fill=_SURFACE, radius=7),
        _box(88, 28, 62, 14, fill=_SURFACE, radius=7),
        _text(32, 50, 200, "Property leads at £8.2m,", size=10, weight=700),
        _text(32, 64, 240, "a 19.5% share of wallet.", size=10, weight=700),
        _bar(32, 88, 120, 8),
        _bar(32, 102, 84, 8, fill="#9db4f5"),
        _bar(32, 116, 48, 8, fill="#c6d3f8"),
        _text(170, 86, 118, "Chart or table —", size=9, color=_MUTED),
        _text(170, 98, 118, "switch inside the", size=9, color=_MUTED),
        _text(170, 110, 118, "same card.", size=9, color=_MUTED),
        _text(32, 138, 260, "Scope · evidence · actions, all in one place.", size=9, color=_MUTED),
    )


def art_verify():
    """The trust drawer: whether every figure is really in the data."""
    return _svg(
        _box(20, 26, 280, 30, fill=_SURFACE),
        _box(32, 34, 96, 14, fill="#dff3e6", stroke="#bfe6cf", radius=7),
        _text(32, 37, 96, "VERIFIED", size=8, weight=800, color=_GOOD, cls="tour-center"),
        _text(138, 37, 150, "How this was calculated", size=9, weight=700),
        _box(20, 62, 280, 96, fill="#ffffff"),
        _text(34, 72, 260, "1  Read the premium data", size=9),
        _text(34, 88, 260, "2  Limited to country Singapore", size=9),
        _text(34, 104, 260, "3  Added up premium", size=9),
        _text(34, 120, 260, "4  Split it by product line", size=9),
        _text(34, 138, 260, "Plain steps — not SQL.", size=9, weight=700, color=_BLUE),
    )


def art_drivers():
    """Explore drivers: what moved, and what pulled the other way."""
    return _svg(
        _text(20, 20, 280, "Premium fell £2.7m. What drove it?", size=10, weight=700),
        _text(20, 38, 280, "Property fell the most — 115% of the movement.", size=9, color=_MUTED),
        _text(20, 66, 70, "Property", size=9),
        _box(96, 62, 180, 14, fill=_SURFACE, radius=4),
        _bar(120, 64, 66, 10, fill="#c53532"),
        _text(96, 84, 70, "Cyber", size=9),
        _box(96, 100, 180, 14, fill=_SURFACE, radius=4),
        _bar(186, 102, 22, 10, fill=_GOOD),
        _text(20, 88, 70, "Cyber", size=9),
        _text(20, 128, 280, "Bars either side of zero: red pulled it down,", size=9, color=_MUTED),
        _text(20, 142, 280, "green pushed back. Computed, not guessed.", size=9, color=_MUTED),
    )


def art_board():
    """Boardroom Mode: the same answer as a board you can edit and export."""
    return _svg(
        _box(20, 22, 280, 132, fill="#ffffff"),
        _box(32, 32, 120, 12, fill=_SURFACE, radius=6),
        _box(32, 54, 74, 40, fill=_SOFT, stroke="#cfdcff"),
        _box(114, 54, 74, 40, fill=_SOFT, stroke="#cfdcff"),
        _box(196, 54, 92, 40, fill=_SOFT, stroke="#cfdcff"),
        _box(32, 104, 256, 38, fill=_SURFACE),
        _bar(44, 116, 40, 8, fill="#9db4f5"),
        _bar(92, 116, 64, 8, fill="#9db4f5"),
        _bar(164, 116, 30, 8, fill="#9db4f5"),
        _text(20, 162, 280, "Turn on Boardroom Mode in the + menu, then export to PowerPoint.",
              size=9, color=_MUTED),
    )


def art_peers():
    """Custom peers: choose the benchmark, and it stays anonymous."""
    return _svg(
        _text(20, 22, 280, "Custom peers", size=11, weight=800),
        _box(20, 44, 280, 26, fill="#ffffff"),
        _text(32, 52, 200, "Zurich  ·  Canada", size=9, weight=700),
        _box(20, 78, 132, 22, fill=_SOFT, stroke="#cfdcff", radius=11),
        _text(20, 84, 132, "5 peers selected", size=9, weight=700, color=_BLUE, cls="tour-center"),
        _text(20, 112, 280, "At least five, so no single carrier can be", size=9, color=_MUTED),
        _text(20, 126, 280, "identified from the benchmark.", size=9, color=_MUTED),
        _text(20, 148, 280, "Peers always read as “Peer 1, Peer 2” in an answer.",
              size=9, weight=700, color=_WARN),
    )


def art_studio():
    """Studio: the same evidence, as a client-ready deck."""
    return _svg(
        _box(20, 26, 130, 128, fill="#ffffff"),
        _text(32, 36, 110, "Studio", size=10, weight=800),
        _box(32, 56, 106, 10, fill=_SURFACE, radius=5),
        _box(32, 72, 106, 10, fill=_SURFACE, radius=5),
        _box(32, 88, 74, 10, fill=_SURFACE, radius=5),
        _box(32, 112, 106, 26, fill=_BLUE, stroke=_BLUE),
        _text(32, 121, 106, "Generate deck", size=9, weight=700, color="#ffffff", cls="tour-center"),
        _box(168, 26, 132, 128, fill="#ffffff"),
        _box(180, 38, 108, 8, fill=_SURFACE, radius=4),
        _box(180, 54, 108, 46, fill=_SOFT, stroke="#cfdcff"),
        _box(180, 108, 108, 8, fill=_SURFACE, radius=4),
        _box(180, 122, 78, 8, fill=_SURFACE, radius=4),
    )


def art_finish():
    """Where to go next."""
    return _svg(
        _text(20, 34, 280, "That's the whole loop:", size=11, weight=800),
        _text(20, 62, 280, "Ask  →  check  →  explore  →  present", size=11, weight=700, color=_BLUE),
        _text(20, 92, 280, "Everything is one question away, and every number", size=9, color=_MUTED),
        _text(20, 106, 280, "can be traced back to the rows it came from.", size=9, color=_MUTED),
        _box(20, 128, 130, 26, fill=_BLUE, stroke=_BLUE),
        _text(20, 136, 130, "Ask your first question", size=9, weight=700,
              color="#ffffff", cls="tour-center"),
    )


@dataclass(frozen=True)
class TourStep:
    """One screen: a title, a sentence, and a drawing of the thing itself."""

    title: str
    body: str
    art: Callable[[], object]


STEPS: Tuple[TourStep, ...] = (
    TourStep(
        "Ask in your own words",
        "No query language and no filters to set up first. Name a carrier, a market "
        "or a product line and ask the question you would ask a colleague. Type “/” "
        "to see the tasks it can do for you.",
        art_ask,
    ),
    TourStep(
        "One answer, everything in it",
        "The finding, the scope it was run under, and the evidence behind it arrive "
        "as a single card. Switch between the chart and the underlying rows without "
        "leaving the answer.",
        art_answer,
    ),
    TourStep(
        "Check any number",
        "Every answer says whether its figures were found in the data, and “How this "
        "was calculated” walks through what was measured, what it was filtered to and "
        "how many rows came back — in plain English.",
        art_verify,
    ),
    TourStep(
        "Ask what drove it",
        "One click decomposes a movement into the slices that caused it, and the ones "
        "that pulled the other way. It is computed from the same rows as the answer, "
        "so the two can never disagree.",
        art_drivers,
    ),
    TourStep(
        "Turn it into a board",
        "Boardroom Mode rebuilds an answer as an editable dashboard — headline "
        "numbers, watchlist, product headroom, industry whitespace — and exports it "
        "to PowerPoint.",
        art_board,
    ),
    TourStep(
        "Choose your benchmark",
        "Pin a custom peer set for the conversation from the + menu. Five is the "
        "minimum, because a benchmark of two carriers is close enough to naming them "
        "— peers always appear anonymised in an answer.",
        art_peers,
    ),
    TourStep(
        "Build the whole deck",
        "The Studio tab uses the same governed data to fill a QBR deck against your "
        "own PowerPoint template, with commentary written from the same evidence.",
        art_studio,
    ),
    TourStep(
        "You're ready",
        "Start anywhere. If an answer is not what you expected, the thumbs-down asks "
        "what went wrong, and that feedback is what tunes it.",
        art_finish,
    ),
)


def step_count() -> int:
    return len(STEPS)
