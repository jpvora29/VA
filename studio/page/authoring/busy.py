"""Studio's busy scope — every reason the Studio pane makes you wait, as data.

One overlay covers the whole workspace and every flag below raises it. The flags are
mounted in ``studio.authoring.layout.studio_chrome``, which is alive for as long as
Studio is: a mode switch REPLACES the whole body, so a flag that lived inside Setup
would have been unmounted at exactly the moment the mode switch needed it.

Adding a new reason to wait is one more :class:`BusyFlag` here plus a ``running=`` on
the callback that owns it — nothing else changes.
"""
from __future__ import annotations

from ui.shell.busy import BusyFlag, BusyScope

# The option cascade + peer panel, the live scope figures, and the deck-section list.
# A single Setup change is answered by all three at once, which is exactly why they are
# three flags: one shared flag would let the fastest one's "finished" lower the overlay
# while a slower sibling was still working.
BUSY_FORM = "qs-busy-form"
BUSY_PREVIEW = "qs-busy-preview"
BUSY_SECTIONS = "qs-busy-sections"

# The master render: a mode switch rebuilds the entire Studio body (Setup's form, the
# Data page's tables, the canvas' slide previews), which is the longest wait in the app
# that is not a build.
BUSY_RENDER = "qs-busy-render"

# The Data page: parsing an upload, saving a mapping, reshaping columns, and promoting a
# dataset to the one the deck is built from.
BUSY_DATA = "qs-busy-data"

# Review: re-running validation and applying the auto-fixes.
BUSY_REVIEW = "qs-busy-review"

# Export: filling and assembling the .pptx to hand back.
BUSY_EXPORT = "qs-busy-export"

# Order matters: the overlay shows the label of the FIRST flag that is up, so the flags
# are declared in the order a user would name what they just did.
STUDIO_BUSY = BusyScope(
    overlay_id="qs-studio-busy",
    flags=(
        # Longer than the default: ``render`` is re-run by every keystroke in the
        # component library's search box as well as by a mode switch, so it has to
        # tolerate a whole fast render, not just a mounted callback answering no_update.
        BusyFlag(BUSY_RENDER, "Opening…", grace_ms=220),
        BusyFlag(BUSY_DATA, "Reading your data…"),
        BusyFlag(BUSY_EXPORT, "Building your PowerPoint…"),
        BusyFlag(BUSY_REVIEW, "Re-checking the deck…"),
        BusyFlag(BUSY_FORM, "Updating your options…"),
        BusyFlag(BUSY_PREVIEW, "Recalculating the scope…"),
        BusyFlag(BUSY_SECTIONS, "Updating the deck outline…"),
    ),
)

__all__ = [
    "STUDIO_BUSY", "BUSY_FORM", "BUSY_PREVIEW", "BUSY_SECTIONS",
    "BUSY_RENDER", "BUSY_DATA", "BUSY_REVIEW", "BUSY_EXPORT",
]
