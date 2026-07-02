"""QBR Studio authoring workspace — runnable, wired to the real DB.

A single hybrid workspace (Setup → Narrative → Canvas → Review → Export) built on
ONE shared, editable document (``studio.page.document``). Generate snapshots the
deterministic ``DeckSpec`` into a document; every edit, reorder, hide, delete and
widget-config change mutates that document; and BOTH the on-screen deck and the
PowerPoint export are produced by ``materialize(doc)`` — so what you edit is what
exports. The document lives in a persisted store, so it survives a refresh.

This file is just the wiring: create the app, set the layout, register each group
of callbacks. The work lives in the ``studio.authoring`` package, one concern per
module (navigation / setup / editing / export).

    python authoring_app.py   →   http://127.0.0.1:8131
"""
from __future__ import annotations

from studio.authoring.editing import register_editing
from studio.authoring.export import register_export
from studio.authoring.layout import build_layout, create_app
from studio.authoring.navigation import register_navigation
from studio.authoring.setup import register_setup

app = create_app()
app.layout = build_layout()

register_navigation(app)   # move between modes, slides, tabs, library panels
register_setup(app)        # Generate the deck, live scope preview
register_editing(app)      # edit fields, pages, widgets, colors on the canvas
register_export(app)       # fill/assemble the template and download the .pptx


if __name__ == "__main__":
    import os

    # Keep debug tracebacks, but DISABLE hot-reload: the long Generate assembly used to
    # trigger a browser reload that reset the in-memory view back to Setup mid-build, so
    # the finished deck never showed. See studio/authoring/layout.py (qs-view now persists).
    app.run(
        debug=True,
        dev_tools_hot_reload=False,
        use_reloader=False,
        port=int(os.environ.get("PORT", "8131")),
    )
