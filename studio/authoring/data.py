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
from typing import Optional, Sequence

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


def seed_mappings(repo, record):
    """Give an upload its PROPOSED mapping, so the HITL step opens pre-filled.

    Proposals only: the record stays ``uploaded`` however complete they look, because a
    mapping governs every number in the deck and a machine guess is not a confirmation.
    The user reviews the rows, changes what is wrong and submits — which is what promotes
    the record and stamps every row ``user``.

    Delegates to ``shape.resync``, so a column the user already decided on keeps that
    decision and only the undecided ones get a proposal.
    """
    from studio.dataset.shape import resync

    return resync(repo, record)


def upload_summary(record, *, truncated: bool = False) -> str:
    """What the upload zone says once a file has landed.

    States the shape AND how much of the mapping is already done, because the proposals
    are the difference between "30 decisions to make" and "3 to check".
    """
    proposed = sum(1 for m in record.mappings if m.target)
    note = f" (truncated to {record.n_rows:,} rows)" if truncated else ""
    return (
        f"Loaded {record.name}: {record.n_rows:,} rows × {record.n_cols} columns{note}. "
        f"{proposed} of {record.n_cols} columns mapped automatically — review below."
    )


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


def add_column(repo, active_id, name, source, recipe, formula) -> Optional[str]:
    """Add a column: read one out of ``source`` with a ``recipe``, else compute a formula.

    A recipe is the common case — "Year from a date" is what unlocks every period
    comparison in the deck when a spreadsheet only carries a billing date. The formula
    path stays for arithmetic over money columns. Returns an error message, or None.
    """
    from studio.dataset import shape

    record = repo.get(active_id) if active_id else None
    if record is None:
        return "No active dataset."
    try:
        if recipe:
            shape.add_derived(repo, record, name or shape.suggested_name(source, recipe),
                              source, recipe)
        else:
            shape.add_computed(repo, record, name, formula)
    except ValueError as exc:
        return str(exc)
    return None


def delete_column(repo, active_id, name) -> bool:
    """Delete any column. A mapped one loses its mapping with it (``shape.drop_column``)."""
    from studio.dataset import shape

    record = repo.get(active_id) if active_id else None
    if record is None:
        return False
    shape.drop_column(repo, record, name)
    return True


def undo_shape(repo, active_id) -> bool:
    """Take back the last column change — the way out of a wrong delete."""
    from studio.dataset import shape

    record = repo.get(active_id) if active_id else None
    if record is None or not record.transforms:
        return False
    shape.undo_last(repo, record)
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
    from studio.dataset.source import dataset_source

    record = repo.get(active_id) if active_id else None
    if record is None:
        return "No active dataset."
    try:
        materialize(repo, record)
    except ValueError as exc:
        return str(exc)
    repo.update_record(replace(record, status="submitted"))
    dataset_source.cache_clear()   # the analytics frames must reflect what was just written
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
            # ``read_upload`` phrases every parse failure for the user (wrong type,
            # empty OneDrive placeholder, missing engine, mislabelled file), so show it.
            log.warning("upload rejected for %s: %s", filename, exc)
            return no_update, html.Span(str(exc), className="qs-map-hint warn")
        except Exception as exc:  # noqa: BLE001 — a broken file must not white-screen the app
            log.warning("upload parse failed for %s: %s", filename, exc)
            return no_update, html.Span(
                f"Could not read {filename!r}: {exc}",
                className="qs-map-hint warn",
            )
        name = (filename or "dataset").rsplit(".", 1)[0]
        repo = get_repository()
        record = seed_mappings(repo, repo.save(frame, name=name, filename=filename or ""))
        return _bump(store, record.dataset_id), html.Span(
            upload_summary(record, truncated=truncated)
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
        dataset_id = ctx.triggered_id["id"]
        repo = get_repository()
        # A dataset saved before auto-mapping existed opens with proposals too.
        seed_mappings(repo, repo.get(dataset_id))
        return _bump(store, dataset_id)

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
        State({"type": "qs-primary", "field": ALL}, "value"),
        State({"type": "qs-primary", "field": ALL}, "id"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def submit_mapping(n, targets, target_ids, descriptions,
                       kpi_names, kpi_ids, kpi_aggs, kpi_fmts, kpi_descs,
                       primary_values, primary_ids, store):
        active = (store or {}).get("active")
        if not n or not active:
            return no_update, no_update
        columns = [ident["col"] for ident in (target_ids or [])]
        kpis = _kpis_from_rows(
            [i["col"] for i in (kpi_ids or [])],
            kpi_names or [], kpi_aggs or [], kpi_fmts or [], kpi_descs or [],
        )
        # Empty when the primary-measure card isn't on screen — which is exactly
        # when a column maps to Premium, so there is no primary measure to declare.
        fields = {i["field"]: v for i, v in zip(primary_ids or [], primary_values or [])}
        primary = _primary_from_fields(
            fields.get("name"), fields.get("column"), fields.get("formula"),
        )
        error = submit_mappings(
            get_repository(), active, columns, targets or [], descriptions or [],
            primary=primary, kpis=kpis,
        )
        if error:
            return no_update, html.Span(error, className="qs-map-hint warn")
        return _bump(store, active), ""

    # ── the column tools ──────────────────────────────────────────────────────

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Output("qs-col-msg", "children"),
        Input("qs-col-add", "n_clicks"),
        State("qs-col-name", "value"),
        State("qs-col-source", "value"),
        State("qs-col-recipe", "value"),
        State("qs-col-formula", "value"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def add_column_cb(n, name, source, recipe, formula, store):
        active = (store or {}).get("active")
        if not n or not active:
            return no_update, no_update
        error = add_column(get_repository(), active, name, source, recipe, formula)
        if error:
            return no_update, html.Span(error, className="qs-map-hint warn")
        return _bump(store, active), ""

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Input({"type": "qs-col-del", "col": ALL}, "n_clicks"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def delete_column_cb(clicks, store):
        active = (store or {}).get("active")
        if not ctx.triggered_id or not any(clicks or []) or not active:
            return no_update
        if not delete_column(get_repository(), active, ctx.triggered_id["col"]):
            return no_update
        return _bump(store, active)

    @app.callback(
        Output("qs-dataset", "data", allow_duplicate=True),
        Input("qs-col-undo", "n_clicks"),
        State("qs-dataset", "data"),
        prevent_initial_call=True,
    )
    def undo_shape_cb(n, store):
        active = (store or {}).get("active")
        if not n or not active or not undo_shape(get_repository(), active):
            return no_update
        return _bump(store, active)

    # ── the pivot builder — PARKED ────────────────────────────────────────────
    # Still switched off (``PIVOT_ENABLED`` in studio/page/authoring/data.py
    # hides its controls). The engine — pivot.py and ``apply_pivot`` above — is kept
    # and tested; re-registering this callback and flipping the flag restores it.
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
