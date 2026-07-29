"""Data mode — upload, HITL column mapping, KPI capture, shape & pivot.

The custom-data workflow: upload → confirm what each column is (mapping +
editable descriptions) → declare KPIs for metric columns that match nothing
canonical → submit → shape (add/delete columns) and pivot → "Use for the deck"
returns to Setup with this data governing generation.

Pure layout: the live callbacks live in ``studio.authoring.data``. The saved
dataset list and the active dataset's frame are read server-side from the
repository, same as Setup reads the template registry.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

import dash_ag_grid as dag
from dash import dcc, html

from studio.dataset.model import (
    REQUIRED_TARGETS,
    ColumnMapping,
    ColumnProfile,
    CustomMeasure,
    DatasetRecord,
)

_PREVIEW_ROWS = 500  # grid preview cap — plenty to eyeball, cheap to ship to the browser

# Uploaded-column kind → bootstrap icon for the mapping rows.
_KIND_ICON = {"number": "bi-123", "text": "bi-fonts", "date": "bi-calendar3"}

_AGG_OPTIONS = [{"label": "Sum", "value": "sum"}, {"label": "Average", "value": "avg"},
                {"label": "Count", "value": "count"}]
_FMT_OPTIONS = [{"label": "Number", "value": "number"}, {"label": "Currency", "value": "currency"},
                {"label": "Percent", "value": "percent"}]


# ── canonical mapping targets (from the flow registry) ───────────────────────


def _target_options() -> List[Mapping[str, str]]:
    """Canonical GPR columns a user column can map onto — entity, temporal, measure."""
    from core.registry import get_flow_registry

    spec = get_flow_registry().get("gpr")
    if spec is None:
        return []
    cols = [c for c in spec.columns.values() if c.role in {"entity", "temporal", "measure"}]
    return [{"label": c.name.replace("_", " "), "value": c.name} for c in cols]


def _target_description(target: str) -> str:
    """The registry's definition for a canonical column (the description seed)."""
    from core.registry import get_flow_registry

    spec = get_flow_registry().get("gpr")
    col = spec.column(target) if (spec and target) else None
    return col.definition if col else ""


# ── upload + saved datasets (the aside) ──────────────────────────────────────


def _upload_zone() -> html.Div:
    return html.Div(
        [
            html.Div([html.I(className="bi bi-cloud-arrow-up"), "Upload data"], className="qs-preview-head"),
            dcc.Upload(
                id="qs-data-upload",
                children=html.Div(
                    [
                        html.I(className="bi bi-file-earmark-spreadsheet qs-data-drop-icon"),
                        html.Div("Drop a .csv or .xlsx here", className="qs-data-drop-title"),
                        html.Div("or click to browse — up to 100k rows", className="qs-data-drop-sub"),
                    ],
                    className="qs-data-drop-inner",
                ),
                multiple=False,
                className="qs-data-drop",
            ),
            html.Div(id="qs-data-upload-msg", className="qs-data-upload-msg"),
        ],
        className="qs-scope-preview",
    )


def _dataset_row(record: DatasetRecord, active: bool) -> html.Div:
    status = {"uploaded": "Needs mapping", "mapped": "Mapped", "submitted": "In use"}.get(
        record.status, record.status
    )
    return html.Div(
        [
            html.Button(
                [
                    html.I(className="bi bi-table qs-ds-icon"),
                    html.Div(
                        [
                            html.Div(record.name, className="qs-ds-name"),
                            html.Div(
                                f"{record.n_rows:,} rows · {record.n_cols} cols · {status}",
                                className="qs-ds-sub",
                            ),
                        ],
                    ),
                ],
                id={"type": "qs-ds-open", "id": record.dataset_id},
                className="qs-ds-open",
            ),
            html.Button(
                html.I(className="bi bi-trash3"),
                id={"type": "qs-ds-delete", "id": record.dataset_id},
                className="qs-ds-delete",
                title="Delete this dataset",
            ),
        ],
        className="qs-ds-row" + (" active" if active else ""),
    )


def _dataset_list(records: Sequence[DatasetRecord], active_id: Optional[str]) -> html.Div:
    if not records:
        body: Any = html.Div(
            [html.I(className="bi bi-inbox"), html.Span("No saved datasets yet.")],
            className="qs-preview-empty",
        )
    else:
        body = html.Div(
            [_dataset_row(r, r.dataset_id == active_id) for r in records],
            className="qs-ds-list",
        )
    return html.Div(
        [
            html.Div([html.I(className="bi bi-collection"), "Saved datasets"], className="qs-aside-card-head"),
            body,
        ],
        className="qs-aside-card",
    )


# ── section chrome ───────────────────────────────────────────────────────────


def _section(icon: str, title: str, sub: str, children: Any) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div([html.I(className=f"bi {icon}"), title], className="qs-sec-title"),
                    html.Div(sub, className="qs-sec-sub") if sub else None,
                ],
                className="qs-sec-head",
            ),
            children,
        ],
        className="qs-setup-section span",
    )


# ── the mapping panel (HITL) ─────────────────────────────────────────────────


def _mapping_for(record: DatasetRecord, column: str) -> Optional[ColumnMapping]:
    return next((m for m in record.mappings if m.uploaded == column), None)


def _mapping_row(profile: ColumnProfile, mapping: Optional[ColumnMapping]) -> html.Div:
    target = mapping.target if mapping else ""
    description = (mapping.description if mapping else "") or _target_description(target)
    sample = " · ".join(profile.sample[:3])
    state_icon = "bi-check-circle-fill ok" if target else "bi-circle"
    return html.Div(
        [
            html.I(className=f"bi {state_icon} qs-map-state"),
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className=f"bi {_KIND_ICON.get(profile.kind, 'bi-fonts')} qs-map-kind"),
                            html.Span(profile.name, className="qs-map-col"),
                        ],
                        className="qs-map-colhead",
                    ),
                    html.Div(
                        f"{profile.n_distinct} distinct · {profile.null_pct}% empty"
                        + (f" · e.g. {sample}" if sample else ""),
                        className="qs-map-colsub",
                    ),
                ],
                className="qs-map-src",
            ),
            html.I(className="bi bi-arrow-right qs-map-arrow"),
            dcc.Dropdown(
                id={"type": "qs-map-target", "col": profile.name},
                options=_target_options(),
                value=target or None,
                placeholder="Not mapped — pick a column",
                className="studio-dd qs-map-dd",
            ),
            dcc.Input(
                id={"type": "qs-map-desc", "col": profile.name},
                value=description,
                placeholder="What this column means…",
                debounce=True,
                className="qs-map-desc",
            ),
        ],
        className="qs-map-row" + (" mapped" if target else ""),
    )


def _mapping_header() -> html.Div:
    return html.Div(
        [
            html.Span(""),
            html.Span("Your column", className="qs-map-h"),
            html.Span(""),
            html.Span("Maps to", className="qs-map-h"),
            html.Span("Description (editable)", className="qs-map-h"),
        ],
        className="qs-map-row qs-map-headrow",
    )


def _mapping_panel(record: DatasetRecord) -> html.Div:
    rows = [_mapping_row(p, _mapping_for(record, p.name)) for p in record.profile.columns]
    mapped_targets = {m.target for m in record.mappings if m.target}
    if record.primary and (record.primary.column or record.primary.formula):
        mapped_targets.add("Premium")
    missing = [t for t in REQUIRED_TARGETS if t not in mapped_targets]
    ready = not missing
    hint = (
        "Every number in the deck traces to these mappings."
        if ready
        else "Required before submit: " + ", ".join(t.replace("_", " ") for t in missing)
    )
    return _section(
        "bi-signpost-2", "Column mapping",
        "Check what each uploaded column is, fix anything wrong, and edit the "
        "descriptions — then submit to unlock pivots and deck generation.",
        html.Div(
            [
                html.Div([_mapping_header(), *rows], className="qs-map-rows"),
                html.Div(
                    [
                        html.Div(hint, className="qs-map-hint" + ("" if ready else " warn")),
                        html.Button(
                            [html.I(className="bi bi-check2-circle"), "Submit mapping"],
                            id="qs-map-submit",
                            className="qs-generate-btn qs-map-submit",
                            disabled=not record.profile.columns,
                        ),
                    ],
                    className="qs-map-actions",
                ),
            ]
        ),
    )


# ── primary measure + custom KPIs ────────────────────────────────────────────


def _numeric_unmapped(record: DatasetRecord) -> List[ColumnProfile]:
    mapped = {m.uploaded for m in record.mappings if m.target}
    return [p for p in record.profile.columns if p.kind == "number" and p.name not in mapped]


def _primary_measure_card(record: DatasetRecord) -> Optional[html.Div]:
    """Shown when nothing maps to Premium: designate or calculate the primary measure."""
    if any(m.target == "Premium" for m in record.mappings):
        return None
    numeric = [{"label": p.name, "value": p.name}
               for p in record.profile.columns if p.kind == "number"]
    primary = record.primary
    return _section(
        "bi-cash-stack", "Primary measure",
        "No column maps to Premium. Pick the money measure that drives the deck — "
        "a column, or a calculation over your columns (e.g. Written_Premium + Fees).",
        html.Div(
            [
                html.Div(
                    [
                        html.Div("NAME", className="studio-field-label"),
                        dcc.Input(
                            id="qs-primary-name",
                            value=(primary.name if primary else ""),
                            placeholder="e.g. Gross Revenue",
                            debounce=True, className="qs-map-desc",
                        ),
                    ],
                    className="qs-kpi-field",
                ),
                html.Div(
                    [
                        html.Div("COLUMN", className="studio-field-label"),
                        dcc.Dropdown(
                            id="qs-primary-col", options=numeric,
                            value=(primary.column or None) if primary else None,
                            placeholder="Pick a numeric column…",
                            className="studio-dd",
                        ),
                    ],
                    className="qs-kpi-field",
                ),
                html.Div(
                    [
                        html.Div("OR CALCULATION", className="studio-field-label"),
                        dcc.Input(
                            id="qs-primary-formula",
                            value=(primary.formula if primary else ""),
                            placeholder="e.g. Written_Premium + Fees",
                            debounce=True, className="qs-map-desc",
                        ),
                    ],
                    className="qs-kpi-field grow",
                ),
            ],
            className="qs-kpi-grid",
        ),
    )


def _kpi_for(record: DatasetRecord, column: str) -> Optional[CustomMeasure]:
    return next((m for m in record.custom_measures if m.column == column), None)


def _kpi_row(profile: ColumnProfile, kpi: Optional[CustomMeasure]) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-123 qs-map-kind"),
                    html.Span(profile.name, className="qs-map-col"),
                ],
                className="qs-map-colhead",
            ),
            dcc.Input(
                id={"type": "qs-kpi-name", "col": profile.name},
                value=(kpi.name if kpi else ""),
                placeholder="KPI name — leave blank to skip",
                debounce=True, className="qs-map-desc",
            ),
            dcc.Dropdown(
                id={"type": "qs-kpi-agg", "col": profile.name},
                options=_AGG_OPTIONS, value=(kpi.aggregation if kpi else "sum"),
                clearable=False, className="studio-dd qs-kpi-dd",
            ),
            dcc.Dropdown(
                id={"type": "qs-kpi-fmt", "col": profile.name},
                options=_FMT_OPTIONS, value=(kpi.format if kpi else "number"),
                clearable=False, className="studio-dd qs-kpi-dd",
            ),
            dcc.Input(
                id={"type": "qs-kpi-desc", "col": profile.name},
                value=(kpi.description if kpi else ""),
                placeholder="How is it calculated / what does it mean?",
                debounce=True, className="qs-map-desc",
            ),
        ],
        className="qs-kpi-row" + (" on" if (kpi and kpi.name) else ""),
    )


def _custom_kpi_card(record: DatasetRecord) -> Optional[html.Div]:
    """Metric columns matching nothing canonical → ask for KPI information."""
    candidates = _numeric_unmapped(record)
    primary_col = record.primary.column if record.primary else ""
    candidates = [p for p in candidates if p.name != primary_col]
    if not candidates:
        return None
    rows = [_kpi_row(p, _kpi_for(record, p.name)) for p in candidates]
    return _section(
        "bi-graph-up-arrow", "Custom KPIs",
        "These numeric columns don't match a standard measure. Name the ones you "
        "want in the deck — they become available in pivots and as slide widgets.",
        html.Div(rows, className="qs-map-rows"),
    )


# ── shape & pivot (after mapping is submitted) ───────────────────────────────


def _column_chips(frame, record: DatasetRecord) -> html.Div:
    """Every working-frame column as a chip; unmapped ones are deletable."""
    mapped = {m.uploaded for m in record.mappings if m.target}
    chips = []
    for col in frame.columns:
        deletable = col not in mapped
        chips.append(
            html.Span(
                [
                    html.Span(str(col), className="qs-colchip-name"),
                    html.Button(
                        html.I(className="bi bi-x"),
                        id={"type": "qs-col-del", "col": str(col)},
                        className="qs-colchip-x",
                        title="Delete this column",
                    ) if deletable else html.I(
                        className="bi bi-link-45deg qs-colchip-lock",
                        title="Mapped column — unmap it before deleting",
                    ),
                ],
                className="qs-colchip" + ("" if deletable else " locked"),
            )
        )
    return html.Div(chips, className="qs-colchip-row")


def _add_column_bar() -> html.Div:
    return html.Div(
        [
            dcc.Input(id="qs-col-name", placeholder="New column name",
                      debounce=False, className="qs-map-desc qs-col-name"),
            dcc.Input(id="qs-col-formula", placeholder="Formula — e.g. Premium * 0.15",
                      debounce=False, className="qs-map-desc qs-col-formula"),
            html.Button([html.I(className="bi bi-plus-lg"), "Add column"],
                        id="qs-col-add", className="qs-tf-addbtn"),
            html.Div(id="qs-col-msg", className="qs-map-hint warn"),
        ],
        className="qs-addcol-bar",
    )


def _pivot_controls(frame, record: DatasetRecord) -> html.Div:
    from studio.dataset.model import PivotSpec

    dims = [{"label": str(c), "value": str(c)} for c in frame.columns]
    numeric_cols = [str(c) for c in frame.select_dtypes("number").columns]
    kpi_names = [m.name for m in record.custom_measures if m.name]
    if record.primary and record.primary.name:
        kpi_names.append(record.primary.name)
    values = [{"label": v, "value": v} for v in dict.fromkeys(numeric_cols + kpi_names)]
    spec = record.pivot or PivotSpec()
    fcol = spec.filters[0][0] if spec.filters else None
    fvals = list(spec.filters[0][1]) if spec.filters else []
    fval_options = (
        [{"label": str(v), "value": str(v)} for v in sorted(frame[fcol].dropna().astype(str).unique())]
        if fcol and fcol in frame.columns else []
    )
    field = lambda label, control: html.Div(  # noqa: E731 — tiny local layout helper
        [html.Div(label, className="studio-field-label"), control], className="qs-kpi-field",
    )
    return html.Div(
        [
            field("ROWS", dcc.Dropdown(id="qs-pivot-rows", options=dims, value=list(spec.rows),
                                       multi=True, placeholder="Group by…", className="studio-dd")),
            field("COLUMNS", dcc.Dropdown(id="qs-pivot-cols", options=dims, value=spec.cols or None,
                                          placeholder="Optional", className="studio-dd")),
            field("VALUES", dcc.Dropdown(id="qs-pivot-values", options=values, value=spec.values or None,
                                         placeholder="Measure…", className="studio-dd")),
            field("AGGREGATION", dcc.Dropdown(id="qs-pivot-agg", options=_AGG_OPTIONS,
                                              value=spec.aggregation, clearable=False, className="studio-dd")),
            field("FILTER COLUMN", dcc.Dropdown(id="qs-pivot-fcol", options=dims, value=fcol,
                                                placeholder="Optional", className="studio-dd")),
            field("FILTER VALUES", dcc.Dropdown(id="qs-pivot-fvals", options=fval_options, value=fvals,
                                                multi=True, placeholder="Keep only…", className="studio-dd")),
            html.Button([html.I(className="bi bi-play-fill"), "Apply pivot"],
                        id="qs-pivot-apply", className="qs-tf-addbtn qs-pivot-apply"),
        ],
        className="qs-pivot-grid",
    )


def _pivot_preview(frame, record: DatasetRecord) -> Any:
    from studio.dataset.pivot import build_pivot

    spec = record.pivot
    if not spec or not spec.is_runnable:
        return html.Div(
            [html.I(className="bi bi-bounding-box"), html.Span("Pick rows and a values column, then Apply.")],
            className="qs-preview-empty",
        )
    try:
        table = build_pivot(frame, spec)
    except ValueError as exc:
        return html.Div([html.I(className="bi bi-exclamation-triangle"), html.Span(str(exc))],
                        className="qs-preview-empty")
    return _grid(table, grid_id="qs-pivot-grid-view", height=320)


def _shape_pivot_section(record: DatasetRecord, frame) -> Optional[html.Div]:
    if record.status not in ("mapped", "submitted") or frame is None:
        return None
    from studio.dataset.materialize import pivot_frame

    enriched = pivot_frame(record, frame)
    in_use = record.status == "submitted"
    cta = html.Div(
        [
            html.Div(
                ("This data is live — Setup and Generate run on it (the pivot's filters scope the rows)."
                 if in_use else
                 "Ready when you are: this makes your data govern the deck — filters, figures and "
                 "commentary all derive from it (the pivot's filters scope the rows)."),
                className="qs-map-hint" + (" ok" if in_use else ""),
            ),
            html.Button(
                [html.I(className="bi bi-rocket-takeoff"),
                 "Update deck data" if in_use else "Use this data for the deck"],
                id="qs-ds-use",
                className="qs-generate-btn qs-map-submit",
            ),
        ],
        className="qs-map-actions",
    )
    return _section(
        "bi-bounding-box", "Shape & pivot",
        "Delete columns you don't need, add calculated ones, and build the pivot "
        "that scopes the deck. The deck still computes from row-level data.",
        html.Div(
            [
                _column_chips(frame, record),
                _add_column_bar(),
                _pivot_controls(enriched, record),
                _pivot_preview(enriched, record),
                cta,
            ],
            className="qs-shape-stack",
        ),
    )


# ── the grid preview ─────────────────────────────────────────────────────────


def _grid(frame, *, grid_id: str = "qs-data-grid", height: int = 480) -> Any:
    if frame is None or frame.empty:
        return html.Div(
            [html.I(className="bi bi-grid-3x2"), html.Span("No rows to preview.")],
            className="qs-preview-empty",
        )
    head = frame.head(_PREVIEW_ROWS)
    return dag.AgGrid(
        id=grid_id,
        rowData=head.to_dict("records"),
        columnDefs=[
            {"field": str(c), "sortable": True, "filter": True, "resizable": True}
            for c in head.columns
        ],
        defaultColDef={"minWidth": 110},
        dashGridOptions={"pagination": True, "paginationPageSize": 25},
        className="ag-theme-alpine qs-data-grid",
        style={"height": f"{height}px", "width": "100%"},
    )


def _active_panel(record: DatasetRecord, frame) -> html.Div:
    n_rows = len(frame) if frame is not None else record.n_rows
    n_preview = min(n_rows, _PREVIEW_ROWS)
    sections = [
        _mapping_panel(record),
        _primary_measure_card(record),
        _custom_kpi_card(record),
        _shape_pivot_section(record, frame),
        _section(
            "bi-grid-3x2", "Data preview",
            f"First {n_preview:,} of {n_rows:,} rows — sort and filter to explore.",
            _grid(frame),
        ),
    ]
    return html.Div([s for s in sections if s is not None], className="qs-data-active")


def _empty_panel() -> html.Div:
    return html.Div(
        [
            html.I(className="bi bi-table qs-empty-icon"),
            html.Div("No dataset selected", className="qs-empty-title"),
            html.P(
                "Upload a spreadsheet or open a saved dataset. You'll confirm what each "
                "column means, then use that data to build the deck — it takes precedence "
                "over the governed database.",
                className="qs-empty-sub",
            ),
        ],
        className="qs-empty",
    )


# ── the mode body ────────────────────────────────────────────────────────────


def data_body(dataset_state: Optional[Mapping[str, Any]]) -> html.Div:
    """The Data mode body. ``dataset_state`` is the ``qs-dataset`` browser store
    (only the active dataset id lives there — data stays server-side)."""
    from studio.dataset.materialize import working_frame
    from studio.dataset.repository import get_repository

    repo = get_repository()
    records = repo.list()
    active_id = (dataset_state or {}).get("active")
    record = repo.get(active_id) if active_id else None
    frame = None
    if record is not None:
        try:
            frame = working_frame(repo, record)
        except ValueError:
            frame = repo.load_frame(active_id)

    aside = html.Div([_upload_zone(), _dataset_list(records, active_id)], className="qs-setup-aside")
    main = _active_panel(record, frame) if record else _empty_panel()
    card = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("QBR Studio", className="qs-setup-eyebrow"),
                            html.Div([html.I(className="bi bi-table"), "Your data"], className="qs-setup-title"),
                            html.P(
                                "Bring your own dataset. Map its columns once, shape it like a "
                                "spreadsheet, and the deck builds from it — figures stay "
                                "deterministic and traceable.",
                                className="qs-setup-sub",
                            ),
                        ],
                        className="qs-setup-head-text",
                    ),
                    html.Span(
                        [html.I(className="bi bi-person-check"), "Your data governs"],
                        className="qs-govern-chip",
                        title="A submitted dataset takes precedence over the governed database for this deck.",
                    ),
                ],
                className="qs-setup-head",
            ),
            html.Div(
                [html.Div(main, className="qs-data-main"), aside],
                className="qs-setup-layout",
            ),
        ],
        className="qs-setup-card",
    )
    return html.Div(card, className="qs-setup-wrap")
