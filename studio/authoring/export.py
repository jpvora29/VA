"""Export + template callbacks: produce the .pptx and edit the filled template.

``export`` serves the deliverable — the assembled deck if we have it, else the
single filled template, else the edited document — all as one ``.pptx``. The
rest edit the template doc: override a slot, add a note, auto-fix, refresh the
sections list, or force validation to re-run.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from dash import ALL, Input, Output, State, ctx, dcc, no_update

from logger import get_logger
from studio.export import export_document
from studio.page import authoring as A
from studio.template_fill import fill_template
from studio.template_fill import validate as TV
from studio.template_fill.model import add_element

from studio.authoring.generate import _assembled_export

log = get_logger(__name__)


def register_export(app):
    """Wire the export + template-editing callbacks onto ``app``."""

    @app.callback(
        Output("studio-pptx-download", "data"),
        Input({"type": "qs-export", "loc": ALL}, "n_clicks"),
        State("qs-selection", "data"),
        State("qs-tdoc", "data"),
        State("qs-doc", "data"),
        prevent_initial_call=True,
    )
    def export(clicks, selection, tdoc, doc):
        if not any(clicks or []):
            return no_update
        # The preview already assembled the deliverable (overall + per product + per country);
        # re-serve that exact file so Export is instant. `_assembled_for` is cached per selection.
        if tdoc and tdoc.get("assembled") and tdoc.get("template_path") and Path(tdoc["template_path"]).exists():
            return dcc.send_file(tdoc["template_path"])
        try:
            assembled = _assembled_export(selection)
        except Exception as exc:  # noqa: BLE001 — fall back rather than white-screen the export
            log.warning("assembled export failed, falling back: %s", exc)
            assembled = None
        if assembled and Path(assembled).exists():
            return dcc.send_file(assembled)
        # Fallback: the single filled template (pre-split behaviour) if assembly can't run.
        if tdoc and tdoc.get("template_path"):
            subject = str((tdoc.get("values") or {}).get("subject_name", "Carrier")).replace(" ", "_")
            out = Path(tempfile.gettempdir()) / f"{subject}_QBR.pptx"
            fill_template(dict(tdoc), out_path=str(out))
            return dcc.send_file(str(out))
        if not doc or not doc.get("order"):
            return no_update
        meta = dict(doc.get("meta") or {})
        carrier = str(meta.get("carrier", "Carrier")).replace(" ", "_")
        country = str(meta.get("country", "Market")).replace(" ", "_")
        suffix = "Executive_Summary" if meta.get("report") == "exec" else "QBR"
        out = Path(tempfile.gettempdir()) / f"{carrier}_{country}_{suffix}.pptx"
        # Pages composed on the canvas export by widget geometry; the rest stay polished.
        export_document(doc, out_path=str(out))
        return dcc.send_file(str(out))

    # ── template editing: slot overrides, added notes, validation re-run ─────────

    @app.callback(
        Output("qs-tdoc", "data", allow_duplicate=True),
        Input({"type": "qs-tf-edit", "key": ALL}, "value"),
        State({"type": "qs-tf-edit", "key": ALL}, "id"),
        State("qs-tdoc", "data"),
        prevent_initial_call=True,
    )
    def edit_slot(values, ids, tdoc):
        if not tdoc or not ids:
            return no_update
        from studio.template_fill.model import materialize_fields

        fields = materialize_fields(dict(tdoc))
        overrides = dict(tdoc.get("overrides", {}))
        changed = False
        for val, ident in zip(values or [], ids or []):
            key = ident["key"]
            if val is None:
                continue
            # Only persist a genuine edit — a value that differs from what the slot
            # already renders. This stops untouched placeholder tokens from being
            # written back as spurious overrides (the false "stale" issues).
            current = str(fields.get(key, {}).get("text", ""))
            if str(val) == current:
                continue
            if overrides.get(key) != val:
                overrides[key] = val
                changed = True
        if not changed:
            return no_update
        return {**tdoc, "overrides": overrides}

    @app.callback(
        Output("qs-tdoc", "data", allow_duplicate=True),
        Input({"type": "qs-tf-add", "slide": ALL}, "n_clicks"),
        State("qs-tdoc", "data"),
        prevent_initial_call=True,
    )
    def add_note(clicks, tdoc):
        if not tdoc or not ctx.triggered_id or not any(clicks or []):
            return no_update
        slide_idx = int(ctx.triggered_id["slide"])
        w = int(tdoc.get("width_emu", 12192000))
        h = int(tdoc.get("height_emu", 6858000))
        el = {"x": w // 12, "y": h // 12, "w": w // 3, "h": h // 10, "text": "New note", "size": 12}
        return add_element(dict(tdoc), slide_idx, el)

    @app.callback(
        Output("qs-tdoc", "data", allow_duplicate=True),
        Input({"type": "qs-tf-autofix"}, "n_clicks"),
        State("qs-tdoc", "data"),
        prevent_initial_call=True,
    )
    def autofix(n, tdoc):
        if not n or not tdoc:
            return no_update
        return TV.auto_fix(dict(tdoc))

    # Template upload was removed: templates are now a fixed, author-made set (assembled
    # per product/country and merged), not user-uploaded. See studio/template_fill/assemble.py.

    @app.callback(
        Output("studio-template-sections", "children"),
        Input("studio-template", "value"),
        Input("studio-data-basis", "value"),
        # Same full-page cue as the other Setup controls: changing either input
        # re-derives the section list, and the user should see that it is happening.
        running=[(Output(A.BUSY_SECTIONS, "className"), A.BUSY_FLAG_ON, A.BUSY_FLAG_CLASS)],
        prevent_initial_call=True,
    )
    def template_sections(scope, basis):
        """Refresh "What's in your QBR" when the scope OR the data basis changes.

        Two inputs because two choices change the deck. The scope carries an axis set
        ("all" → overall + product + country); the basis decides whether each country
        block is followed by a Carrier Survey page. The panel lists every axis the pair
        assembles — see ``A.deck_axes``, which mirrors ``assemble.plan_subdecks``.
        """
        if not scope:
            return no_update
        return A.template_sections_panel(scope, basis)

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-tf-revalidate"}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def revalidate(n, view):
        # Validation is computed live on every render; bumping a nonce forces a re-run.
        if not n:
            return no_update
        view = dict(view or {})
        view["revalidate"] = int(view.get("revalidate", 0)) + 1
        return view
