"""Export + template callbacks: produce the .pptx and edit the filled template.

``export`` serves the deliverable — the assembled deck if we have it, else the
single filled template, else the edited document — all as one ``.pptx``. The
rest edit the template doc: override a slot, add a note, auto-fix, or force
validation to re-run. (The deck's page list moved to ``studio.authoring.setup``,
where the rest of the Setup form's callbacks live.)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from dash import ALL, Input, Output, State, ctx, dcc, no_update

from logger import get_logger
from studio.export import export_document
from studio.template_fill import fill_template
from studio.template_fill import registry
from studio.template_fill import text_edits as TE
from studio.template_fill import validate as TV
from studio.template_fill.fill import apply_text_overrides
from studio.template_fill.model import add_element

from studio.authoring.generate import _assembled_export
from studio.page.authoring.busy import BUSY_EXPORT, BUSY_REVIEW
from ui.shell.busy import busy_running

log = get_logger(__name__)


def _delivered_text(tdoc, key: str):
    """What the delivered file says in the box at ``key``, so a revert is recognised.

    ``derive_manifest`` is cached by content-hash, so this is a dictionary lookup on
    every commit but the first for a given build.
    """
    address = TE.parse_address(key)
    path = (tdoc or {}).get("template_path")
    if address is None or not path:
        return None
    try:
        template, _ = registry.derive_manifest(path)
    except Exception as exc:  # noqa: BLE001 — an unreadable deck is not an edit failure
        log.warning("could not read the delivered deck to check an edit: %s", exc)
        return None
    shape = template.shape(address.slide_idx, address.shape_id)
    block = TE.editable_text(shape, address.slide_idx, {}) if shape is not None else None
    return block.original if block else None


def _with_retyped_text(tdoc) -> str:
    """The assembled file to send: the cached build, or a copy carrying the edits.

    Export re-serves the assembled deck straight off disk, so text retyped in the
    edit field would never reach the .pptx. The edits are written into a COPY — the
    cached build stays the build, so exporting again after a reset is still clean.
    """
    src = tdoc["template_path"]
    edits = TE.text_edits(tdoc)
    if not edits:
        return src
    out = Path(tempfile.gettempdir()) / f"{Path(src).stem}_edited.pptx"
    try:
        return apply_text_overrides(src, edits, str(out))
    except Exception as exc:  # noqa: BLE001 — an edit must never cost the export
        log.warning("could not apply %d retyped box(es), sending the build: %s", len(edits), exc)
        return src


def register_export(app):
    """Wire the export + template-editing callbacks onto ``app``."""

    @app.callback(
        Output("studio-pptx-download", "data"),
        Input({"type": "qs-export", "loc": ALL}, "n_clicks"),
        State("qs-selection", "data"),
        State("qs-tdoc", "data"),
        State("qs-doc", "data"),
        prevent_initial_call=True,
        # Filling and assembling the deliverable takes seconds at best, and the click
        # produces nothing on screen until the browser's download prompt appears.
        running=busy_running(BUSY_EXPORT),
    )
    def export(clicks, selection, tdoc, doc):
        if not any(clicks or []):
            return no_update
        # The preview already assembled the deliverable (overall + per product + per country);
        # re-serve that exact file so Export is instant — carrying whatever the author
        # retyped on the canvas. `_assembled_for` is cached per selection.
        if tdoc and tdoc.get("assembled") and tdoc.get("template_path") and Path(tdoc["template_path"]).exists():
            return dcc.send_file(_with_retyped_text(tdoc))
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

    # ── the delivered deck's own words: pick one on the slide, edit it here ──────

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-tf-pick", "at": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def pick_text(clicks, view):
        """Clicking a text box on the slide opens it in the edit field."""
        if not ctx.triggered_id or not any(clicks or []):
            return no_update
        view = dict(view or {})
        view["tf_sel"] = ctx.triggered_id["at"]
        return view

    @app.callback(
        Output("qs-tdoc", "data", allow_duplicate=True),
        Input({"type": "qs-tf-block", "at": ALL}, "n_blur"),
        State({"type": "qs-tf-block", "at": ALL}, "value"),
        State({"type": "qs-tf-block", "at": ALL}, "id"),
        State("qs-tdoc", "data"),
        prevent_initial_call=True,
    )
    def edit_text(_blurs, values, ids, tdoc):
        if not tdoc or not ctx.triggered_id:
            return no_update
        key = ctx.triggered_id["at"]
        value = next((v for v, i in zip(values or [], ids or []) if i == ctx.triggered_id), None)
        original = _delivered_text(tdoc, key)
        if original is None:
            return no_update
        updated = TE.set_text_edit(tdoc, key, value, original=original)
        return no_update if updated == dict(tdoc) else updated

    @app.callback(
        Output("qs-tdoc", "data", allow_duplicate=True),
        Input({"type": "qs-tf-reset", "at": ALL}, "n_clicks"),
        State("qs-tdoc", "data"),
        prevent_initial_call=True,
    )
    def reset_text(clicks, tdoc):
        if not tdoc or not ctx.triggered_id or not any(clicks or []):
            return no_update
        return TE.clear_text_edit(tdoc, ctx.triggered_id["at"])

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
        running=busy_running(BUSY_REVIEW),
    )
    def autofix(n, tdoc):
        if not n or not tdoc:
            return no_update
        return TV.auto_fix(dict(tdoc))

    # Template upload was removed: templates are now a fixed, author-made set (assembled
    # per product/country and merged), not user-uploaded. See studio/template_fill/assemble.py.

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-tf-revalidate"}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
        running=busy_running(BUSY_REVIEW),
    )
    def revalidate(n, view):
        # Validation is computed live on every render; bumping a nonce forces a re-run.
        if not n:
            return no_update
        view = dict(view or {})
        view["revalidate"] = int(view.get("revalidate", 0)) + 1
        return view
