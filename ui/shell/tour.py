"""The guided tour — what this application is, and how to work it.

New users arrive at a prompt box and guess what it can do, and most guess low:
they type a lookup, get a number, and never find out about the evidence panel,
the drivers decomposition, Boardroom Mode or Studio. A tour is the cheapest fix
for that, and it only works if it SHOWS rather than tells — so every step carries
a drawn illustration of the thing it is describing, not a paragraph about it.

The first version was a flat reel of eight screens with one sentence each, and
the report on it was fair: it said what existed without teaching anyone to use
it. Three things changed.

**It has chapters.** Twelve screens in a row is a slideshow; four named chapters
is a map. The rail down the side shows the whole shape of the product before the
reader has seen any of it, and lets someone who only came for Boardroom Mode go
straight there. Getting started → Reading an answer → Going deeper → Sharing it.

**Each step says how, not just what.** A sentence introduces the feature; two or
three numbered points say what to actually do — which button, which menu, what
happens next. That is the difference between a tour and a manual page.

**Most steps can be tried on the spot.** A step that carries `try_it` gets a
button that drops that question into the composer and closes the tour, so the
first thing a new user does is ask a real question rather than read about asking
one. Onboarding that ends in a working answer is onboarding people finish.

The illustrations are drawn from the app's own design tokens. That is deliberate:
a screenshot goes stale the first time a button moves, has to be re-shot per
theme, and adds binary files to the repo. A drawn panel stays true to the SHAPE
of the UI without pretending to be a photograph of it.

Steps are data. Adding one is adding a `TourStep` to `STEPS`; the chapters, the
dots, the counter and the navigation all read from that list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

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

# The four chapters, in the order someone learns the product.
GETTING_STARTED = "Getting started"
READING = "Reading an answer"
DEEPER = "Going deeper"
SHARING = "Sharing the work"


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


def _pill(x, y, w, label, *, fill=_SOFT, stroke=_SOFT, color=_BLUE, size=9):
    """A chip with its label centred — the shape half the interface is made of."""
    return [
        _box(x, y, w, 20, fill=fill, stroke=stroke, radius=10),
        _text(x, y + 5, w, label, size=size, weight=700, color=color, cls="tour-center"),
    ]


# ── the illustrations ────────────────────────────────────────────────────────


def art_workspaces():
    """The four workspaces behind one navbar."""
    return _svg(
        _box(14, 20, 292, 30, fill="#ffffff"),
        # The navbar's real order, so the picture and the product agree.
        *_pill(22, 25, 58, "Studio", fill=_SURFACE, stroke=_LINE, color=_INK),
        *_pill(86, 25, 58, "Chatbot", fill=_BLUE, stroke=_BLUE, color="#ffffff"),
        *_pill(150, 25, 58, "Recap", fill=_SURFACE, stroke=_LINE, color=_INK),
        *_pill(214, 25, 58, "MoM", fill=_SURFACE, stroke=_LINE, color=_INK),
        _box(14, 60, 292, 100, fill="#ffffff"),
        _text(26, 72, 270, "Ask a question, and the answer arrives here.", size=9),
        _bar(26, 92, 150, 8),
        _bar(26, 106, 210, 8, fill="#9db4f5"),
        _bar(26, 120, 110, 8, fill="#c6d3f8"),
        _text(26, 138, 270, "Everything you build is kept when you switch tabs.",
              size=9, color=_MUTED),
    )


def art_ask():
    """The composer: type a question the way you would say it."""
    return _svg(
        _box(20, 26, 280, 62, fill="#ffffff"),
        _text(34, 40, 210, "Which product lines is Zurich"),
        _text(34, 54, 210, "growing fastest in Canada?"),
        _box(258, 42, 28, 28, fill=_BLUE, stroke=_BLUE, radius=14),
        _text(258, 50, 28, "↑", size=13, weight=800, color="#ffffff", cls="tour-center"),
        *_pill(20, 100, 84, "/brief"),
        *_pill(110, 100, 90, "/compare"),
        *_pill(206, 100, 94, "/whitespace"),
        _text(20, 132, 280, "Type “/” to see every task it can do for you.",
              size=9, color=_MUTED),
    )


def art_scope():
    """Who, where and when — and the one question it asks when they are missing."""
    return _svg(
        _text(20, 18, 280, "Every answer states the scope it ran under", size=10, weight=800),
        *_pill(20, 40, 74, "Zurich"),
        *_pill(100, 40, 74, "Canada"),
        *_pill(180, 40, 60, "2024"),
        _box(20, 76, 280, 50, fill="#ffffff"),
        _text(32, 86, 250, "Which carrier should I look at?", size=9, weight=700),
        _text(32, 102, 250, "Asked once, when it genuinely cannot tell.",
              size=9, color=_MUTED),
        _text(20, 138, 280, "Name them in the question, or answer the prompt.",
              size=9, color=_MUTED),
    )


def art_answer():
    """One card: the finding, its scope, and the evidence under it."""
    return _svg(
        _box(20, 14, 280, 150, fill="#ffffff"),
        _box(32, 24, 52, 14, fill=_SURFACE, radius=7),
        _box(88, 24, 62, 14, fill=_SURFACE, radius=7),
        _text(32, 46, 210, "Property leads at $8.2m,", size=10, weight=700),
        _text(32, 60, 240, "a 19.5% share of wallet.", size=10, weight=700),
        _bar(32, 84, 120, 8),
        _bar(32, 98, 84, 8, fill="#9db4f5"),
        _bar(32, 112, 48, 8, fill="#c6d3f8"),
        _text(170, 82, 120, "Scope, finding,", size=9, color=_MUTED),
        _text(170, 94, 120, "evidence, drivers", size=9, color=_MUTED),
        _text(170, 106, 120, "and what to do next", size=9, color=_MUTED),
        _text(170, 118, 120, "— one card.", size=9, color=_MUTED),
        _box(32, 136, 256, 1, fill=_LINE, stroke=_LINE, radius=0),
        _text(32, 144, 256, "Copy · Explore drivers · Export · View as board",
              size=8.5, color=_MUTED),
    )


def art_evidence():
    """The rows behind the picture, in the same card."""
    return _svg(
        *_pill(20, 18, 62, "Chart", fill=_BLUE, stroke=_BLUE, color="#ffffff"),
        *_pill(88, 18, 62, "Table"),
        _box(20, 48, 280, 112, fill="#ffffff"),
        _text(32, 58, 120, "Product line", size=8.5, weight=800, color=_MUTED),
        _text(200, 58, 88, "Premium", size=8.5, weight=800, color=_MUTED),
        _text(32, 76, 120, "Property", size=9),
        _text(200, 76, 88, "$8.2m", size=9, weight=700),
        _text(32, 94, 120, "Casualty", size=9),
        _text(200, 94, 88, "$5.1m", size=9, weight=700),
        _text(32, 112, 120, "Cyber", size=9),
        _text(200, 112, 88, "$1.8m", size=9, weight=700),
        _text(32, 136, 256, "The exact rows the answer was written from.",
              size=9, color=_MUTED),
    )


def art_verify():
    """The trust drawer: how the number was made, and whether it is real."""
    return _svg(
        _box(18, 14, 284, 28, fill=_SURFACE),
        _box(28, 21, 92, 14, fill="#dff3e6", stroke="#bfe6cf", radius=7),
        _text(28, 24, 92, "VERIFIED", size=8, weight=800, color=_GOOD, cls="tour-center"),
        _text(128, 24, 160, "Source & calculation", size=9, weight=700),
        _box(18, 48, 284, 116, fill="#ffffff"),
        _text(30, 56, 264, "1  Started with the premium records", size=8.5),
        _text(30, 72, 264, "2  Narrowed it to Canada and 2024", size=8.5),
        _text(30, 88, 264, "3  Added up premium for each product line", size=8.5),
        _text(30, 104, 264, "4  That left 3 product lines to report on",
              size=8.5, weight=800, color=_GOOD),
        _box(30, 124, 264, 28, fill=_SURFACE, radius=6),
        _text(40, 133, 60, "$8.2m", size=9, weight=800),
        _text(180, 133, 106, "Found in the data", size=8.5, weight=700, color=_GOOD),
    )


def art_edit():
    """Your words, over the model's — and the check runs again."""
    return _svg(
        _box(20, 20, 280, 92, fill="#ffffff"),
        _text(32, 32, 250, "Property leads at $8.2m, and is the", size=9.5),
        _text(32, 48, 250, "line to protect at renewal.", size=9.5),
        _bar(174, 46, 2, 13, fill=_BLUE, radius=1),
        _box(32, 74, 92, 22, fill=_BLUE, stroke=_BLUE, radius=6),
        _text(32, 81, 92, "Save", size=9, weight=700, color="#ffffff", cls="tour-center"),
        _box(132, 74, 78, 22, fill=_SURFACE, radius=6),
        _text(132, 81, 78, "Cancel", size=9, weight=700, color=_INK, cls="tour-center"),
        _text(20, 124, 280, "Edit the wording and the figure check runs again,",
              size=9, color=_MUTED),
        _text(20, 138, 280, "so the badge always describes what is on screen.",
              size=9, color=_MUTED),
    )


def art_drivers():
    """Explore drivers: what moved, and what pulled the other way."""
    return _svg(
        _text(20, 16, 280, "Premium fell $2.7m. What drove it?", size=10, weight=700),
        _text(20, 34, 280, "Property fell the most — 115% of the movement.",
              size=9, color=_MUTED),
        _text(20, 62, 68, "Property", size=9),
        _box(92, 58, 184, 14, fill=_SURFACE, radius=4),
        _bar(118, 60, 66, 10, fill="#c53532"),
        _text(20, 90, 68, "Cyber", size=9),
        _box(92, 86, 184, 14, fill=_SURFACE, radius=4),
        _bar(184, 88, 24, 10, fill=_GOOD),
        _bar(184, 52, 1, 56, fill=_LINE, radius=0),
        _text(20, 122, 280, "Bars either side of zero: red pulled it down,",
              size=9, color=_MUTED),
        _text(20, 136, 280, "green pushed back. Computed, never guessed.",
              size=9, color=_MUTED),
    )


def art_peers():
    """Custom peers: choose the benchmark, and it stays anonymous."""
    return _svg(
        _text(20, 16, 280, "Custom peers", size=11, weight=800),
        _box(20, 38, 280, 26, fill="#ffffff"),
        _text(32, 46, 200, "Zurich  ·  Canada", size=9, weight=700),
        *_pill(20, 72, 132, "5 peers selected"),
        _text(20, 104, 280, "At least five, so no single carrier can be",
              size=9, color=_MUTED),
        _text(20, 118, 280, "identified from the benchmark.", size=9, color=_MUTED),
        _text(20, 142, 280, "Peers read as “Peer 1, Peer 2” in every answer.",
              size=9, weight=700, color=_WARN),
    )


def art_board():
    """Boardroom Mode: the same answer as a board you can edit and export."""
    return _svg(
        _box(20, 18, 280, 128, fill="#ffffff"),
        _box(32, 28, 120, 12, fill=_SURFACE, radius=6),
        _box(32, 50, 74, 40, fill=_SOFT, stroke="#cfdcff"),
        _box(114, 50, 74, 40, fill=_SOFT, stroke="#cfdcff"),
        _box(196, 50, 92, 40, fill=_SOFT, stroke="#cfdcff"),
        _box(32, 100, 256, 34, fill=_SURFACE),
        _bar(44, 112, 40, 8, fill="#9db4f5"),
        _bar(92, 112, 64, 8, fill="#9db4f5"),
        _bar(164, 112, 30, 8, fill="#9db4f5"),
        _text(20, 156, 280, "Drag the widgets, then export the board to PowerPoint.",
              size=9, color=_MUTED),
    )


def art_studio():
    """Studio: the same evidence, as a client-ready deck."""
    return _svg(
        _box(20, 20, 130, 132, fill="#ffffff"),
        _text(32, 30, 110, "Studio", size=10, weight=800),
        _box(32, 50, 106, 10, fill=_SURFACE, radius=5),
        _box(32, 66, 106, 10, fill=_SURFACE, radius=5),
        _box(32, 82, 74, 10, fill=_SURFACE, radius=5),
        _box(32, 108, 106, 26, fill=_BLUE, stroke=_BLUE),
        _text(32, 117, 106, "Generate deck", size=9, weight=700,
              color="#ffffff", cls="tour-center"),
        _box(168, 20, 132, 132, fill="#ffffff"),
        _box(180, 32, 108, 8, fill=_SURFACE, radius=4),
        _box(180, 48, 108, 46, fill=_SOFT, stroke="#cfdcff"),
        _box(180, 102, 108, 8, fill=_SURFACE, radius=4),
        _box(180, 116, 78, 8, fill=_SURFACE, radius=4),
        _text(20, 160, 280, "Your own template, filled from the same governed data.",
              size=9, color=_MUTED),
    )


def art_finish():
    """Where to go next."""
    return _svg(
        _text(20, 28, 280, "That's the whole loop:", size=11, weight=800),
        _text(20, 54, 280, "Ask  →  check  →  explore  →  present",
              size=11, weight=700, color=_BLUE),
        _text(20, 84, 280, "Every number can be traced back to the rows it",
              size=9, color=_MUTED),
        _text(20, 98, 280, "came from, and the tour is in the navbar whenever",
              size=9, color=_MUTED),
        _text(20, 112, 280, "you want it again.", size=9, color=_MUTED),
        _box(20, 130, 138, 26, fill=_BLUE, stroke=_BLUE),
        _text(20, 138, 138, "Ask your first question", size=9, weight=700,
              color="#ffffff", cls="tour-center"),
    )


@dataclass(frozen=True)
class TourStep:
    """One screen of the tour.

    `body` introduces the idea; `points` say what to actually do with it, which
    is the half the first version was missing. `try_it`, where a step has one, is
    a real question the reader can send without typing anything.
    """

    title: str
    body: str
    art: Callable[[], object]
    chapter: str = GETTING_STARTED
    points: Tuple[str, ...] = field(default_factory=tuple)
    try_it: str = ""


@dataclass(frozen=True)
class Chapter:
    """A named run of consecutive steps, and where it starts."""

    name: str
    start: int
    size: int


STEPS: Tuple[TourStep, ...] = (
    TourStep(
        "One place for the whole account",
        "Four workspaces behind one navbar. Studio builds a QBR deck from the data, "
        "Chat answers questions about it, Recap reads past review decks into a recap, and "
        "MoM drafts minutes. Nothing is thrown away when you move between them.",
        art_workspaces,
        chapter=GETTING_STARTED,
        points=(
            "Switch workspace from the tabs at the top — a half-written question or a "
            "half-built deck is still there when you come back.",
            "Everything reads from the same governed data, so a figure in Chat and the "
            "same figure in a deck cannot disagree.",
            "This tour is always in the navbar under “Take a tour”.",
        ),
    ),
    TourStep(
        "Ask in your own words",
        "No query language, and no filters to set up first. Name a carrier, a market or "
        "a product line and ask the question you would ask a colleague.",
        art_ask,
        chapter=GETTING_STARTED,
        points=(
            "Type “/” in the box to see every task it can do — /brief, /compare, "
            "/explain, /trend, /rank and /whitespace.",
            "A slash command is just a question with the wording already written, so you "
            "can edit it before you send it.",
            "Follow-ups keep the thread: “and the year before?” works.",
        ),
        try_it="Which product lines is Zurich growing fastest in Canada?",
    ),
    TourStep(
        "Say who, where and when",
        "Answers are scoped to a carrier, a market and a period. Name them in the "
        "question and it runs straight away; leave them all out and it asks you one "
        "short question rather than guessing.",
        art_scope,
        chapter=GETTING_STARTED,
        points=(
            "The scope it used is printed on the answer itself, so you can see what a "
            "figure covers without scrolling back up.",
            "Change any part of it by asking again — “same thing for Singapore”.",
            "Nothing is remembered against you: each question states its own scope.",
        ),
        try_it="How did Marsh-placed premium move in Singapore last year?",
    ),
    TourStep(
        "One answer, everything in it",
        "The finding, the scope it ran under, the evidence behind it and what to do next "
        "arrive as a single card — not as a paragraph with attachments underneath.",
        art_answer,
        chapter=READING,
        points=(
            "The first line is the finding; the labelled groups under it are the "
            "supporting points, so you can stop reading when you have what you need.",
            "The row along the bottom is what you can do with the answer: copy it, "
            "explore the drivers, export the data, or open it as a board.",
            "Thumbs-down asks what went wrong, and that is what tunes it.",
        ),
    ),
    TourStep(
        "See the evidence behind it",
        "Every answer that ran a query carries the result with it. Switch between the "
        "chart and the underlying rows inside the same card.",
        art_evidence,
        chapter=READING,
        points=(
            "“Table” shows the exact rows the answer was written from — not a summary "
            "of them.",
            "Where a turn ran more than one query, each result gets its own tab.",
            "“Export data” takes the rows straight to a spreadsheet.",
        ),
    ),
    TourStep(
        "Check any number",
        "Open “Source & calculation” under any answer. It walks through what we did "
        "to the data, one step at a time, and then lists every figure in the answer with "
        "a verdict beside it.",
        art_verify,
        chapter=READING,
        points=(
            "The steps are in plain English — where the data came from, what it was "
            "narrowed to, what was added up, and what came out of it.",
            "The badge says Verified, Partly verified or Not verified. Partly verified "
            "names the figures the data did not contain and says what that means.",
            "The technical query is still there, one more click down, if you want it.",
        ),
    ),
    TourStep(
        "Make the wording yours",
        "The commentary is a draft, not a verdict. Click the pencil and edit it in "
        "place — the chart, the figures and the evidence stay exactly where they are.",
        art_edit,
        chapter=READING,
        points=(
            "Headings and bullet points survive the edit; you are editing the answer, "
            "not a box of raw text.",
            "Saving re-runs the figure check over your words, so the badge always "
            "describes what is on screen.",
            "Type a number the data does not contain and it will say so.",
        ),
    ),
    TourStep(
        "Ask what drove it",
        "“Explore drivers” decomposes a movement into the slices that caused it, and the "
        "ones that pulled the other way. It is computed from the same rows as the "
        "answer above it, so the two can never disagree.",
        art_drivers,
        chapter=DEEPER,
        points=(
            "The lead line says which slice moved most and what offset it, before you "
            "read a single bar.",
            "A share over 100% is real: one slice fell further than the total because "
            "another was pushing back.",
            "It is instant — no second question, and no extra model call.",
        ),
        try_it="What drove the change in Marsh-placed premium in Canada last year?",
    ),
    TourStep(
        "Choose your benchmark",
        "Pin a custom peer set for the conversation from the Tools menu beside the "
        "composer, which also states which set is in force. "
        "Five is the minimum, because a benchmark of two carriers is close enough to "
        "naming them.",
        art_peers,
        chapter=DEEPER,
        points=(
            "Peers are set per market, so a Canadian peer group and a Singaporean one "
            "can be different carriers.",
            "Once a subject carrier is named, every other carrier reads as “Peer 1, "
            "Peer 2” — carrier-facing output never names a peer.",
            "A pure market ranking with no subject still names the carriers: there is "
            "nothing confidential about a league table.",
        ),
    ),
    TourStep(
        "Turn it into a board",
        "Boardroom Mode rebuilds an answer as an editable dashboard — headline numbers, "
        "the watchlist, product headroom and industry whitespace — instead of a "
        "paragraph.",
        art_board,
        chapter=DEEPER,
        points=(
            "Turn it on in the Tools menu beside the composer, or use “View as board” on an "
            "answer you already have.",
            "Drag the widgets to reorder them, and edit any widget in place.",
            "Every widget keeps the evidence behind it, so a board is as checkable as "
            "an answer.",
        ),
        try_it="Give me a board on Zurich in Canada for the last full year",
    ),
    TourStep(
        "Build the whole deck",
        "The Studio tab fills a QBR deck against your own PowerPoint template, with "
        "commentary written from the same governed evidence as the answers in Chat.",
        art_studio,
        chapter=SHARING,
        points=(
            "Set the scope on the Setup page, tick the pages you want, and Generate.",
            "Upload your own template and it is analysed for slots and mapped — you do "
            "not have to rebuild the deck to match ours.",
            "The Review page says why a field came out blank, rather than leaving you "
            "to work it out from the slide.",
        ),
    ),
    TourStep(
        "You're ready",
        "Ask, check, explore, present. Start anywhere — the tour is in the navbar "
        "whenever you want it again.",
        art_finish,
        chapter=SHARING,
        points=(
            "If an answer is not what you expected, the thumbs-down asks what went "
            "wrong, and that feedback is what tunes it.",
            "Anything you build survives a tab switch and a reload.",
        ),
        try_it="Brief me on Zurich in Canada",
    ),
)


def step_count() -> int:
    return len(STEPS)


def chapters() -> List[Chapter]:
    """The chapters, derived from the steps rather than declared twice.

    A chapter is a run of consecutive steps sharing a name, so reordering `STEPS`
    reorders the rail with no second list to keep in step.
    """
    out: List[Chapter] = []
    for index, step in enumerate(STEPS):
        if out and out[-1].name == step.chapter:
            last = out[-1]
            out[-1] = Chapter(last.name, last.start, last.size + 1)
        else:
            out.append(Chapter(step.chapter, index, 1))
    return out


def chapter_of(index: int) -> str:
    """Which chapter a step index belongs to."""
    return STEPS[index].chapter if 0 <= index < len(STEPS) else ""


def try_it_questions() -> Dict[int, str]:
    """The step indexes that carry a ready-made question, and the question."""
    return {i: step.try_it for i, step in enumerate(STEPS) if step.try_it}
