"""DeckSpec — the shared slide contract for screen rendering AND PPT export.

A QBR is a `DeckSpec`: an ordered list of `SlideSpec`s, each a `layout` plus typed
`Block`s (KPIs, chart, table, commentary, bullets, callout). The SAME spec drives:

  - the on-screen PPT-like deck (`studio/page/slide.py`), and
  - the PPTX export (`studio/export/ppt.py`), which maps each block to a template
    placeholder via a `LayoutMap` (`studio/export/template.py`).

Because content is decoupled into typed blocks, supporting a more complex .pptx
template is purely extending the block→placeholder mapping — no change to compute,
rules, or rendering. This is the "block contract" from DESIGN.md §2, realised.

Pure data (stdlib dataclasses): no Dash, no python-pptx — both renderers import it,
neither leaks into it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


# ── blocks ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Block:
    """Base block. `kind` is the dispatch key for both renderers."""

    kind: str


@dataclass(frozen=True)
class KpiBlock(Block):
    items: Sequence[Mapping[str, Any]] = ()  # [{label, value, delta?, tone?, icon?}]

    def __init__(self, items):  # keep `kind` implicit
        object.__setattr__(self, "kind", "kpis")
        object.__setattr__(self, "items", list(items))


@dataclass(frozen=True)
class ChartBlock(Block):
    chart: str = "bar"          # bar | donut
    labels: Sequence[str] = ()
    values: Sequence[float] = ()
    title: str = ""

    def __init__(self, chart, labels, values, title=""):
        object.__setattr__(self, "kind", "chart")
        object.__setattr__(self, "chart", chart)
        object.__setattr__(self, "labels", list(labels))
        object.__setattr__(self, "values", list(values))
        object.__setattr__(self, "title", title)


@dataclass(frozen=True)
class TableBlock(Block):
    columns: Sequence[Mapping[str, str]] = ()
    rows: Sequence[Mapping[str, Any]] = ()
    hidden: int = 0
    title: str = ""

    def __init__(self, columns, rows, hidden=0, title=""):
        object.__setattr__(self, "kind", "table")
        object.__setattr__(self, "columns", list(columns))
        object.__setattr__(self, "rows", list(rows))
        object.__setattr__(self, "hidden", hidden)
        object.__setattr__(self, "title", title)


@dataclass(frozen=True)
class CommentaryBlock(Block):
    headline: str = ""
    points: Sequence[Mapping[str, Any]] = ()   # [{label, text, tone}]
    actions: Sequence[str] = ()

    def __init__(self, headline, points, actions=()):
        object.__setattr__(self, "kind", "commentary")
        object.__setattr__(self, "headline", headline)
        object.__setattr__(self, "points", list(points))
        object.__setattr__(self, "actions", list(actions))


@dataclass(frozen=True)
class BulletsBlock(Block):
    items: Sequence[str] = ()
    title: str = ""

    def __init__(self, items, title=""):
        object.__setattr__(self, "kind", "bullets")
        object.__setattr__(self, "items", list(items))
        object.__setattr__(self, "title", title)


@dataclass(frozen=True)
class CalloutBlock(Block):
    text: str = ""
    tone: str = "neutral"

    def __init__(self, text, tone="neutral"):
        object.__setattr__(self, "kind", "callout")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "tone", tone)


@dataclass(frozen=True)
class SwotBlock(Block):
    """Four quadrants, each a list of short strings."""

    strengths: Sequence[str] = ()
    weaknesses: Sequence[str] = ()
    opportunities: Sequence[str] = ()
    threats: Sequence[str] = ()

    def __init__(self, strengths=(), weaknesses=(), opportunities=(), threats=()):
        object.__setattr__(self, "kind", "swot")
        object.__setattr__(self, "strengths", list(strengths))
        object.__setattr__(self, "weaknesses", list(weaknesses))
        object.__setattr__(self, "opportunities", list(opportunities))
        object.__setattr__(self, "threats", list(threats))


@dataclass(frozen=True)
class CardsBlock(Block):
    """Strategic-initiative cards: [{tag, title, body, tone}]."""

    cards: Sequence[Mapping[str, Any]] = ()

    def __init__(self, cards):
        object.__setattr__(self, "kind", "cards")
        object.__setattr__(self, "cards", list(cards))


# ── advanced visuals (premium-derived; shared by the screen + PPT renderers) ──


@dataclass(frozen=True)
class MatrixBlock(Block):
    """Opportunity bubble matrix: points = [{label, x, y, size}] (ease × potential)."""

    points: Sequence[Mapping[str, Any]] = ()
    title: str = ""

    def __init__(self, points, title=""):
        object.__setattr__(self, "kind", "matrix")
        object.__setattr__(self, "points", list(points))
        object.__setattr__(self, "title", title)


@dataclass(frozen=True)
class HeatmapBlock(Block):
    """Portfolio heatmap: rows × columns grid of normalised 0–100 values."""

    rows: Sequence[str] = ()
    columns: Sequence[str] = ()
    values: Sequence[Sequence[float]] = ()
    title: str = ""

    def __init__(self, rows, columns, values, title=""):
        object.__setattr__(self, "kind", "heatmap")
        object.__setattr__(self, "rows", list(rows))
        object.__setattr__(self, "columns", list(columns))
        object.__setattr__(self, "values", [list(r) for r in values])
        object.__setattr__(self, "title", title)


@dataclass(frozen=True)
class RadarBlock(Block):
    """Competitive-position radar: labels (axes) + 0–100 values."""

    labels: Sequence[str] = ()
    values: Sequence[float] = ()
    title: str = ""

    def __init__(self, labels, values, title=""):
        object.__setattr__(self, "kind", "radar")
        object.__setattr__(self, "labels", list(labels))
        object.__setattr__(self, "values", list(values))
        object.__setattr__(self, "title", title)


@dataclass(frozen=True)
class TimelineBlock(Block):
    """Initiative gantt: tasks = [{task, start, duration, status, owner}]."""

    tasks: Sequence[Mapping[str, Any]] = ()
    title: str = ""

    def __init__(self, tasks, title=""):
        object.__setattr__(self, "kind", "timeline")
        object.__setattr__(self, "tasks", list(tasks))
        object.__setattr__(self, "title", title)


# ── slides & deck ─────────────────────────────────────────────────────────────

# Layout names map to a template layout on export and to a CSS grid on screen.
# The QBR workhorse is `insight`: action title + left commentary rail + right visual.
LAYOUTS = frozenset(
    {"cover", "exec", "insight", "swot", "initiatives", "decision", "methodology",
     "agenda", "divider"}
)


@dataclass(frozen=True)
class SlideSpec:
    layout: str
    title: str = ""            # the action title — a takeaway sentence, not a topic
    subtitle: str = ""
    eyebrow: str = ""
    accent: str = "blue"
    # Left-rail commentary present on every content slide: [{label?, text, tone}].
    takeaways: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    blocks: Sequence[Block] = field(default_factory=tuple)  # the right-side / main visual
    # Decision-orientation (every content slide answers a question + recommends).
    question: str = ""
    implication: str = ""
    recommendation: str = ""
    owner: Optional[str] = None
    due_date: Optional[str] = None
    confidence: str = ""       # high | medium | low
    evidence: Sequence[Mapping[str, Any]] = field(default_factory=tuple)  # [{label,value,detail}]
    sources: Sequence[str] = field(default_factory=tuple)
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeckSpec:
    slides: Sequence[SlideSpec] = field(default_factory=tuple)
    meta: Mapping[str, Any] = field(default_factory=dict)  # carrier, country, year, title…

    def __len__(self) -> int:
        return len(self.slides)
