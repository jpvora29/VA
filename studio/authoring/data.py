"""Data-tab callbacks: upload, mapping + KPI submit, shape, pivot, use-for-deck.

Every handler writes the ``qs-dataset`` browser store, which holds ONLY
``{"source": governed|custom, "active": <dataset id>, "rev": <n>}`` — the data
itself stays server-side in the dataset repository. The master render callback
watches the store, so any change here re-renders the Data tab (and Setup's
data-source banner) from the repository's state.

The module-level helpers hold the real logic with the repository injected, so
every path is testable without a running Dash app; the callbacks are thin.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from typing import List, Optional, Sequence

from dash import ALL, Input, Output, State, ctx, html, no_update

from logger import get_logger
from studio.dataset.ingest import read_upload
from studio.dataset.model import (
    ColumnMapping,
    CustomMeasure,
    PivotSpec,
    record_complete,
    undescribed_unmapped,
)
from studio.dataset.repository import get_repository

log = get_logger(__name__)


def _decode_upload(contents: str) -> bytes:
    """``dcc.Upload.contents`` is ``data:<mime>;base64,<payload>`` — return the bytes."""
    _, _, payload = (contents or "").partition("base64,")
    return base64.b64decode(payload or "")


def _bump(store, active_id, **extra):
    """The next store value: source + active id + a revision to force a re-render."""
    store = store or {}
    out = {
        "source": store.get("source", "governed"),
        "active": active_id,
        "rev": int(store.get("rev", 0)) + 1,
    }
    out.update(extra)
    return out


# ── testable helpers (repository injected) ───────────────────────────────────


def _primary_from_fields(name, column, formula) -> Optional[CustomMeasure]:
    if not (column or formula):
        return None
    return CustomMeasure(
        name=str(name or column or "Primary measure"),
        column=str(column or ""),
        formula=str(formula or ""),
        aggregation="sum",
        format="currency",
    )


def _kpis_from_rows(columns, names, aggs, fmts, descs) -> tuple:
    """Declared KPIs = rows where the user typed a name."""
    out = []
    for col, name, agg, fmt, desc in zip(columns, names, aggs, fmts, descs):
        if str(name or "").strip():
            out.append(CustomMeasure(
                name=str(name).strip(), column=str(col),
                aggregation=str(agg or "sum"), format=str(fmt or "number"),
                description=str(desc or ""),
            ))
    return tuple(out)


def submit_mappings(
    repo, active_id, columns, targets, descriptions,
    *, primary: Optional[CustomMeasure] = None, kpis: Sequence[CustomMeasure] = (),
) -> Optional[str]:
    """Persist the full HITL submission: mappings, primary measure, custom KPIs.

    Returns an error message, or None on success. Every unmapped column must
    carry a description — with no canonical target, the description is the only
    thing that says what the column means. The record reaches ``mapped`` once
    Premium (directly or via the primary measure), Carrier_Group and Year are
    covered; otherwise the work is saved but stays ``uploaded``."""
    record = repo.get(active_id) if active_id else None
    if record is None:
        return "No active dataset."
    mappings = tuple(
        ColumnMapping(
            uploaded=col,
            target=str(target or ""),
            description=str(desc or ""),
            source="user",
        )
        for col, target, desc in zip(columns, targets, descriptions)
    )
    missing = undescribed_unmapped(mappings)
    if missing:
        shown = ", ".join(missing[:4]) + ("…" if len(missing) > 4 else "")
        return f"Describe every unmapped column before submitting: {shown}"
    updated = replace(
        record, mappings=mappings, primary=primary, custom_measures=tuple(kpis),
    )
    status = "mapped" if record_complete(updated) else "uploaded"
    repo.update_record(replace(updated, status=status))
    return None


def add_column(repo, active_id, name, formula) -> Optional[str]:
    """Append an add-column op to the recipe. Returns an error message or None."""
    from studio.dataset.materialize import working_frame
    from studio.dataset.model import TransformOp
    from studio.dataset.transform import apply_transforms

    record = repo.get(active_id) if active_id else None
    if record is None:
        return "No active dataset."
    name = str(name or "").strip()
    if not name:
        return "Give the new column a name."
    op = TransformOp(kind="add", name=name, formula=str(formula or ""))
    try:
        frame = working_frame(repo, record)
        apply_transforms(frame, [op])  # validate before persisting
    except ValueError as exc:
        return str(exc)
    repo.update_record(replace(record, transforms=(*record.transforms, op)))
    return None


def delete_column(repo, active_id, name) -> bool:
    """Append a drop op — mapped columns are protected (unmap first)."""
    from studio.dataset.model import TransformOp

    record = repo.get(active_id) if active_id else None
    if record is None:
        return False
    if name in {m.uploaded for m in record.mappings if m.target}:
        return False
    op = TransformOp(kind="drop", name=str(name))
    repo.update_record(replace(record, transforms=(*record.transforms, op)))
    return True


def apply_pivot(repo, active_id, rows, cols, values, agg, fcol, fvals) -> bool:
    """Persist the pivot spec (rows/cols/values/agg + one filter)."""
    record = repo.get(active_id) if active_id else None
    if record is None:
        return False
    filters = ((str(fcol), tuple(str(v) for v in (fvals or []))),) if fcol and fvals else ()
    spec = PivotSpec(
        rows=tuple(rows or ()), cols=str(cols or ""), values=str(values or ""),
        aggregation=str(agg or "sum"), filters=filters,
    )
    repo.update_record(replace(record, pivot=spec))
    return True


def use_for_deck(repo, active_id) -> Optional[str]:
    """Materialize the canonical table and mark the dataset submitted.

    Returns an error message, or None on success."""
    from studio.dataset.materialize import materialize

    record = repo.get(active_id) if active_id else None
    if record is None:
        return "No active dataset."
    try:
        materialize(repo, record)
    except ValueError as exc:
        return str(exc)
    repo.update_record(replace(record, status="submitted"))
    return None


# ── callbacks ────────────────────────────────────────────────────────────────


def register_data(app):
    """Wire the Data-tab + data-source callbacks onto ``app``."""

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Input("studio-data-source", "value"),
        State("qs-dataset", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def choose_source(source, store, view):
        """The Setup toggle. Picking "My data" routes to the Data page unless a
        submitted dataset is already active (then Setup just flips source)."""
        store = store or {}
        if not source or source == store.get("source", "governed"):
            return no_update, no_update
        new_store = _bump(store, store.get("active"), source=source)
        record = get_repository().get(store.get("active") or "") if source == "custom" else None
        if source == "custom" and (record is None or record.status != "submitted"):
            view = dict(view or {})
            view["mode"] = "data"
            return new_store, view
        return new_store, no_update

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Output("qs-data-upload-msg", "children"),
        Input("qs-data-upload", "contents"),
        State("qs-data-upload", "filename"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def upload(contents, filename, store):
        if not contents:
            return no_update, no_update
        try:
            frame, truncated = read_upload(filename or "", _decode_upload(contents))
        except ValueError as exc:
            return no_update, html.Span(str(exc), className="qs-map-hint warn")
        except Exception as exc:  # noqa: BLE001 — a broken file must not white-screen the app
            log.warning("upload parse failed for %s: %s", filename, exc)
            return no_update, html.Span(
                f"Could not read {filename!r} — is it a valid spreadsheet?",
                className="qs-map-hint warn",
            )
        name = (filename or "dataset").rsplit(".", 1)[0]
        record = get_repository().save(frame, name=name, filename=filename or "")
        note = f" (truncated to {record.n_rows:,} rows)" if truncated else ""
        return _bump(store, record.dataset_id), html.Span(
            f"Loaded {record.name}: {record.n_rows:,} rows × {record.n_cols} columns{note}."
        )

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Input({"type": "qs-ds-open", "id": ALL}, "n_clicks"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def open_dataset(clicks, store):
        if not ctx.triggered_id or not any(clicks or []):
            return no_update
        return _bump(store, ctx.triggered_id["id"])

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Input({"type": "qs-ds-delete", "id": ALL}, "n_clicks"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def delete_dataset(clicks, store):
        if not ctx.triggered_id or not any(clicks or []):
            return no_update
        dataset_id = ctx.triggered_id["id"]
        get_repository().delete(dataset_id)
        active = (store or {}).get("active")
        return _bump(store, None if active == dataset_id else active)

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Output("qs-map-msg", "children"),
        Input("qs-map-submit", "n_clicks"),
        State({"type": "qs-map-target", "col": ALL}, "value"),
        State({"type": "qs-map-target", "col": ALL}, "id"),
        State({"type": "qs-map-desc", "col": ALL}, "value"),
        State({"type": "qs-kpi-name", "col": ALL}, "value"),
        State({"type": "qs-kpi-name", "col": ALL}, "id"),
        State({"type": "qs-kpi-agg", "col": ALL}, "value"),
        State({"type": "qs-kpi-fmt", "col": ALL}, "value"),
        State({"type": "qs-kpi-desc", "col": ALL}, "value"),
        State("qs-primary-name", "value"),
        State("qs-primary-col", "value"),
        State("qs-primary-formula", "value"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def submit_mapping(n, targets, target_ids, descriptions,
                       kpi_names, kpi_ids, kpi_aggs, kpi_fmts, kpi_descs,
                       primary_name, primary_col, primary_formula, store):
        active = (store or {}).get("active")
        if not n or not active:
            return no_update, no_update
        columns = [ident["col"] for ident in (target_ids or [])]
        kpis = _kpis_from_rows(
            [i["col"] for i in (kpi_ids or [])],
            kpi_names or [], kpi_aggs or [], kpi_fmts or [], kpi_descs or [],
        )
        primary = _primary_from_fields(primary_name, primary_col, primary_formula)
        error = submit_mappings(
            get_repository(), active, columns, targets or [], descriptions or [],
            primary=primary, kpis=kpis,
        )
        if error:
            return no_update, html.Span(error, className="qs-map-hint warn")
        return _bump(store, active), ""

    # ── shape & pivot callbacks — PARKED ──────────────────────────────────────
    # Column add/delete and the pivot builder are switched off for now
    # (``SHAPE_TOOLS_ENABLED`` in studio/page/authoring/data.py hides their
    # controls). The engine — transform.py, pivot.py, and the helpers above —
    # is kept, tested and ready; re-registering these three callbacks and
    # flipping the flag turns the feature back on.
    #
    # @app.callback(
    #     Output("qs-dataset", "data", allow_duplicate=True),
    #     Output("qs-col-msg", "children"),
    #     Input("qs-col-add", "n_clicks"),
    #     State("qs-col-name", "value"),
    #     State("qs-col-formula", "value"),
    #     State("qs-dataset", "data"),
    #     prevent_initial_call=True,
    # )
    # def add_column_cb(n, name, formula, store):
    #     active = (store or {}).get("active")
    #     if not n or not active:
    #         return no_update, no_update
    #     error = add_column(get_repository(), active, name, formula)
    #     if error:
    #         return no_update, error
    #     return _bump(store, active), ""
    #
    # @app.callback(
    #     Output("qs-dataset", "data", allow_duplicate=True),
    #     Input({"type": "qs-col-del", "col": ALL}, "n_clicks"),
    #     State("qs-dataset", "data"),
    #     prevent_initial_call=True,
    # )
    # def delete_column_cb(clicks, store):
    #     active = (store or {}).get("active")
    #     if not ctx.triggered_id or not any(clicks or []) or not active:
    #         return no_update
    #     if not delete_column(get_repository(), active, ctx.triggered_id["col"]):
    #         return no_update
    #     return _bump(store, active)
    #
    # @app.callback(
    #     Output("qs-dataset", "data", allow_duplicate=True),
    #     Input("qs-pivot-apply", "n_clicks"),
    #     State("qs-pivot-rows", "value"),
    #     State("qs-pivot-cols", "value"),
    #     State("qs-pivot-values", "value"),
    #     State("qs-pivot-agg", "value"),
    #     State("qs-pivot-fcol", "value"),
    #     State("qs-pivot-fvals", "value"),
    #     State("qs-dataset", "data"),
    #     prevent_initial_call=True,
    # )
    # def apply_pivot_cb(n, rows, cols, values, agg, fcol, fvals, store):
    #     active = (store or {}).get("active")
    #     if not n or not active:
    #         return no_update
    #     if not apply_pivot(get_repository(), active, rows, cols, values, agg, fcol, fvals):
    #         return no_update
    #     return _bump(store, active)

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Output("qs-data-upload-msg", "children", allow_duplicate=True),
        Input("qs-ds-use", "n_clicks"),
        State("qs-dataset", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def use_for_deck_cb(n, store, view):
        """Materialize + submit, flip the source to custom, return to Setup."""
        active = (store or {}).get("active")
        if not n or not active:
            return no_update, no_update, no_update
        error = use_for_deck(get_repository(), active)
        if error:
            return no_update, no_update, html.Span(error, className="qs-map-hint warn")
        view = dict(view or {})
        view["mode"] = "setup"
        return _bump(store, active, source="custom"), view, ""
