"""Collision-free placement of point labels on a scatter panel — pure geometry, no pptx.

A data label can only be told LEFT / RIGHT / ABOVE / BELOW of its point, which cannot
untangle a cluster: three lines of business at rank 1 with similar pools put three names
in the same place whatever sides they get. Here every label is a box in the panel's own
coordinates, and each is placed in turn at the first candidate spot that is inside the
plot and clear of every label already placed and every point marker — beside its point
first, then a line above or below, then further out. The fill engine then pins each label
to the box it was given (``fill._place_rank_labels``).

All units are the caller's (EMU in practice). Deterministic: same input, same layout.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def centre(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2

    def overlap(self, other: Box) -> float:
        """The area this box shares with ``other`` (0 when apart or only touching)."""
        w = min(self.x1, other.x1) - max(self.x0, other.x0)
        h = min(self.y1, other.y1) - max(self.y0, other.y0)
        return w * h if w > 0 and h > 0 else 0.0

    def inside(self, bounds: Box) -> bool:
        return (
            self.x0 >= bounds.x0
            and self.x1 <= bounds.x1
            and self.y0 >= bounds.y0
            and self.y1 <= bounds.y1
        )


@dataclass(frozen=True)
class LabelSpec:
    """One label to place: its point (anchor) and the size of its text."""

    x: float
    y: float
    width: float
    height: float


# How far up or down a label may move, in lines, nearest first.
_LINE_SHIFTS = (0, -1, 1, -2, 2, -3, 3, -4, 4)


def place_labels(
    labels: Sequence[LabelSpec], bounds: Box, *, gap: float, marker: float
) -> list[Box]:
    """A box for every label, in input order (earlier labels get first pick).

    ``gap`` is the space kept between a point and the name beside it; ``marker`` is the
    half-width of a point's marker, which no label may cover.
    """
    markers = [
        Box(s.x - marker, s.y - marker, s.x + marker, s.y + marker) for s in labels
    ]
    placed: list[Box] = []
    for i, spec in enumerate(labels):
        obstacles = placed + [m for j, m in enumerate(markers) if j != i]
        placed.append(_best_spot(spec, bounds, obstacles, gap + marker))
    return placed


def _best_spot(spec: LabelSpec, bounds: Box, obstacles: list[Box], reach: float) -> Box:
    """The first clear candidate inside the plot, else the one that collides least."""
    candidates = [box for box in _candidates(spec, bounds, reach) if box.inside(bounds)]
    for box in candidates:
        if not any(box.overlap(o) for o in obstacles):
            return box
    if candidates:
        return min(candidates, key=lambda box: sum(box.overlap(o) for o in obstacles))
    return _clamped(_beside(spec, reach, right=True, shift=0), bounds)


def _candidates(spec: LabelSpec, bounds: Box, reach: float) -> list[Box]:
    """Spots to try, nearest first: beside the point, then a line up or down, and so on.

    The preferred side is the right, unless the name would run off the plot there.
    """
    right_first = spec.x + reach + spec.width <= bounds.x1
    out: list[Box] = []
    for shift in _LINE_SHIFTS:
        sides = [right_first, not right_first]
        out.extend(_beside(spec, reach, right=side, shift=shift) for side in sides)
        if shift:
            out.insert(len(out) - 1, _centred(spec, shift))
    return out


def _beside(spec: LabelSpec, reach: float, *, right: bool, shift: int) -> Box:
    cy = spec.y + shift * spec.height
    x0 = spec.x + reach if right else spec.x - reach - spec.width
    return Box(x0, cy - spec.height / 2, x0 + spec.width, cy + spec.height / 2)


def _centred(spec: LabelSpec, shift: int) -> Box:
    cy = spec.y + shift * spec.height
    return Box(
        spec.x - spec.width / 2,
        cy - spec.height / 2,
        spec.x + spec.width / 2,
        cy + spec.height / 2,
    )


def _clamped(box: Box, bounds: Box) -> Box:
    """``box`` slid back inside ``bounds`` (a name wider than the plot keeps its left edge)."""
    dx = max(bounds.x0 - box.x0, 0) or min(bounds.x1 - box.x1, 0)
    dy = max(bounds.y0 - box.y0, 0) or min(bounds.y1 - box.y1, 0)
    return Box(box.x0 + dx, box.y0 + dy, box.x1 + dx, box.y1 + dy)
