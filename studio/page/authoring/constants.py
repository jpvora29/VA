"""Shared constants for the authoring shell (modes, theme colors, zoom bounds)."""
from __future__ import annotations

from typing import List, Mapping, Tuple

# ── global product modes (blueprint §"Global Product Modes"). Setup is the
#    entry point — its data-source choice routes to Data (upload → map → pivot)
#    when the user brings their own dataset. Export is no longer a mode — its
#    summary + download live in Review, and the top-bar button remains. ─────────
MODES: List[Mapping[str, str]] = [
    {"id": "setup", "label": "Setup", "icon": "bi-sliders2", "hint": "Scope & data"},
    {"id": "data", "label": "Data", "icon": "bi-table", "hint": "Upload & shape data"},
    {"id": "canvas", "label": "Canvas", "icon": "bi-grid-1x2", "hint": "Compose pages"},
    {"id": "review", "label": "Review", "icon": "bi-patch-check", "hint": "Client-ready & export"},
]

THEME_COLORS: Tuple[Tuple[str, str], ...] = (
    ("#000F47", "Navy"),
    ("#0B4BFF", "Blue"),
    ("#00A8E0", "Cyan"),
    ("#007A78", "Teal"),
    ("#1F9D55", "Green"),
    ("#B9810A", "Amber"),
    ("#C53532", "Red"),
    ("#5B6577", "Slate"),
    ("#EEF3FF", "Blue tint"),
    ("#FFFFFF", "White"),
)
STANDARD_COLORS: Tuple[Tuple[str, str], ...] = (
    ("#000000", "Black"),
    ("#7F7F7F", "Gray"),
    ("#C00000", "Dark red"),
    ("#FF0000", "Red"),
    ("#FFC000", "Gold"),
    ("#FFFF00", "Yellow"),
    ("#92D050", "Light green"),
    ("#00B050", "Green"),
    ("#00B0F0", "Light blue"),
    ("#7030A0", "Purple"),
)

ZOOM_MIN = 40
ZOOM_MAX = 130
ZOOM_STEP = 5
ZOOM_FIT = 65

# Story-item states → (css token, human label). A subset of the blueprint's
# "Story Item States" that we can derive deterministically from slide content.
_STATUS_LABEL = {
    "approved": "Approved",
    "client-ready": "Client-ready",
    "needs-review": "Needs review",
    "needs-evidence": "Needs evidence",
    "draft": "Draft",
    "ready": "Ready",
    "appendix": "Appendix",
}
