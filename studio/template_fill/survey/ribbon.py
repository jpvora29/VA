"""The "Peers Ranked by Survey Scores" ribbon — a spec in, a PNG out.

The author drew this page's chart with think-cell and pasted the RESULT as a picture, so
there is no chart to refill: the page is filled by rendering our own image at the authored
picture's exact frame and swapping the blob (see :mod:`studio.template_fill.fill`).

The shape of the chart is a bump/ribbon: one COLUMN per survey section, each a rank-ordered
stack of score boxes (best at the top), with a curved band joining the same carrier's box
across adjacent columns so a reader follows one carrier's rank left to right. The deck's
subject is blue; every peer is grey and unnamed — ``flows.yaml`` sets
``peer_names_allowed: false`` for the survey flow, so a box carries its SCORE and nothing else.

Pure: no data access, no I/O beyond the render itself.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)

# Sampled from the authored picture so a refilled chart is indistinguishable in style.
CARRIER_FILL = "#7BBCFC"
CARRIER_BAND = "#BBDDFE"
PEER_FILL = "#BCB9B4"
PEER_BAND = "#DDDBD9"
SCORE_TEXT = "#FFFFFF"
AXIS_TEXT = "#444444"
TITLE_TEXT = "#222222"

# The authored picture's pixel size — the render matches it so the swap needs no rescale.
WIDTH_PX = 1162
HEIGHT_PX = 303

TITLE = "Peers Ranked by Survey Scores (Section level)"

# Layout, as fractions of the image. A box occupies under half its column's pitch so the
# ribbons have room to cross; the plot band stops short of the bottom to leave the wrapped
# section labels somewhere to sit.
_BOX_SHARE = 0.46
_ROW_SHARE = 0.74
_PLOT_TOP = 0.88
_PLOT_BOTTOM = 0.24
_LABEL_WRAP = 18


@dataclass(frozen=True)
class RibbonBox:
    """One carrier's score in one section. ``highlight`` marks the deck's subject."""

    carrier: str
    score: float
    highlight: bool = False


@dataclass(frozen=True)
class RibbonColumn:
    """One section's ranking — ``boxes`` ordered best score first."""

    label: str
    boxes: Tuple[RibbonBox, ...] = ()


@dataclass(frozen=True)
class RibbonSpec:
    """Everything the renderer needs: the columns, the title, and the output size."""

    columns: Tuple[RibbonColumn, ...] = ()
    title: str = TITLE
    width_px: int = WIDTH_PX
    height_px: int = HEIGHT_PX


def available() -> bool:
    """Whether a PNG can actually be rendered on this host (kaleido + a browser)."""
    try:
        import kaleido  # noqa: F401
    except ImportError:
        return False
    return True


# ── geometry (pure) ──────────────────────────────────────────────────────────


def _wrap(label: str) -> str:
    return "<br>".join(textwrap.wrap(str(label), width=_LABEL_WRAP) or [""])


def _row_count(spec: RibbonSpec) -> int:
    return max((len(c.boxes) for c in spec.columns), default=0)


def _metrics(spec: RibbonSpec) -> Tuple[float, float, float, float]:
    """``(column pitch, half box width, row pitch, half box height)`` in 0..1 coords."""
    pitch = 1.0 / max(len(spec.columns), 1)
    rows = max(_row_count(spec), 1)
    row_pitch = (_PLOT_TOP - _PLOT_BOTTOM) / rows
    return pitch, pitch * _BOX_SHARE / 2.0, row_pitch, row_pitch * _ROW_SHARE / 2.0


def _box_rect(spec: RibbonSpec, col: int, row: int) -> Tuple[float, float, float, float]:
    """One box's ``(left, bottom, right, top)``."""
    pitch, half_w, row_pitch, half_h = _metrics(spec)
    cx = (col + 0.5) * pitch
    cy = _PLOT_TOP - (row + 0.5) * row_pitch
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h


def _band_path(x0: float, y0t: float, y0b: float,
               x1: float, y1t: float, y1b: float) -> str:
    """An SVG path for one ribbon: two mirrored cubic beziers closed into a band."""
    xm = (x0 + x1) / 2.0
    return (f"M {x0},{y0t} C {xm},{y0t} {xm},{y1t} {x1},{y1t} "
            f"L {x1},{y1b} C {xm},{y1b} {xm},{y0b} {x0},{y0b} Z")


# ── figure ───────────────────────────────────────────────────────────────────


def _ranks(spec: RibbonSpec) -> List[Dict[str, int]]:
    """Per column, ``{carrier: its row index}`` — what a band needs at both ends."""
    return [{b.carrier: i for i, b in enumerate(col.boxes)} for col in spec.columns]


def _band_shapes(spec: RibbonSpec, ranks: List[Dict[str, int]], *, highlight: bool) -> List[dict]:
    """The ribbons for the subject (``highlight``) or for the peers.

    Split so the caller can add the peers' first and the subject's last: shapes paint in
    insertion order, and the carrier's own thread must read on top of the grey ones.
    """
    out: List[dict] = []
    for i in range(len(spec.columns) - 1):
        for carrier, r0 in ranks[i].items():
            r1 = ranks[i + 1].get(carrier)
            if r1 is None or spec.columns[i].boxes[r0].highlight is not highlight:
                continue
            _, y0b, x0, y0t = _box_rect(spec, i, r0)
            x1, y1b, _, y1t = _box_rect(spec, i + 1, r1)
            out.append(dict(
                type="path", xref="paper", yref="paper",
                path=_band_path(x0, y0t, y0b, x1, y1t, y1b),
                fillcolor=(CARRIER_BAND if highlight else PEER_BAND),
                line=dict(width=0), layer="below",
            ))
    return out


def _box_shapes_and_labels(spec: RibbonSpec) -> Tuple[List[dict], List[dict]]:
    """Every score box and the score printed inside it."""
    shapes: List[dict] = []
    labels: List[dict] = []
    for i, column in enumerate(spec.columns):
        for j, box in enumerate(column.boxes):
            x0, y0, x1, y1 = _box_rect(spec, i, j)
            shapes.append(dict(
                type="rect", xref="paper", yref="paper", x0=x0, y0=y0, x1=x1, y1=y1,
                fillcolor=(CARRIER_FILL if box.highlight else PEER_FILL),
                line=dict(width=0), layer="above",
            ))
            labels.append(dict(
                xref="paper", yref="paper", x=(x0 + x1) / 2.0, y=(y0 + y1) / 2.0,
                text=f"{box.score:.1f}", showarrow=False, xanchor="center", yanchor="middle",
                font=dict(family="Arial", size=11, color=SCORE_TEXT),
            ))
    return shapes, labels


def _axis_labels(spec: RibbonSpec) -> List[dict]:
    """The section name under each column (wrapped — some run to four words)."""
    pitch, *_ = _metrics(spec)
    return [
        dict(xref="paper", yref="paper", x=(i + 0.5) * pitch, y=_PLOT_BOTTOM - 0.04,
             text=_wrap(column.label), showarrow=False, xanchor="center", yanchor="top",
             font=dict(family="Arial", size=11, color=AXIS_TEXT))
        for i, column in enumerate(spec.columns)
    ]


def build_figure(spec: RibbonSpec):
    """The plotly figure for ``spec`` — separated from the render so it is unit-testable."""
    import plotly.graph_objects as go

    ranks = _ranks(spec)
    boxes, scores = _box_shapes_and_labels(spec)
    shapes = (_band_shapes(spec, ranks, highlight=False)
              + _band_shapes(spec, ranks, highlight=True)
              + boxes)
    title = dict(xref="paper", yref="paper", x=0.0, y=1.0, text=spec.title,
                 showarrow=False, xanchor="left", yanchor="top",
                 font=dict(family="Arial", size=13, color=TITLE_TEXT))

    fig = go.Figure()
    fig.update_layout(
        shapes=shapes,
        annotations=scores + _axis_labels(spec) + [title],
        xaxis=dict(visible=False, range=[0, 1], fixedrange=True),
        yaxis=dict(visible=False, range=[0, 1], fixedrange=True),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="white", plot_bgcolor="white", showlegend=False,
    )
    return fig


def render_ribbon_png(spec: RibbonSpec) -> bytes:
    """``spec`` rendered to PNG bytes at twice the authored picture's pixel size.

    Raises whatever kaleido raises — the caller decides whether a missing renderer means
    "keep the authored picture" (the page) or "fail the test" (the suite).
    """
    return build_figure(spec).to_image(
        format="png", width=spec.width_px, height=spec.height_px, scale=2)
